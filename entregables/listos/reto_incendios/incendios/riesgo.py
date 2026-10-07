"""
Riesgo meteorológico de incendios forestales — previsión oficial de AEMET.

AEMET OpenData lo publica a diario (`incendios/mapasriesgo/previsto/dia/{1,2,3}`)
solo como IMAGEN PNG: mañana, pasado y el día siguiente, validez 12 UTC; no hay
mapa del día en curso. Aquí se convierte esa imagen en un raster utilizable:

1. Georreferencia. El mapa está en Mercator. Su extensión se ajustó una vez
   (2026-10-07) maximizando la coincidencia entre la tierra coloreada de la
   imagen y el contorno GISCO de España: IoU 0,986. Leaflet usa Web Mercator,
   así que el raster se superpone sin reproyectar.
2. Clasificación. Cada píxel se asigna a uno de los 6 niveles de la leyenda por
   su tono (el sombreado de relieve de la imagen oscurece, pero no cambia el
   tono). Las líneas de límites provinciales se rellenan con el nivel vecino.

Si AEMET cambia el diseño del mapa (tamaño o encuadre), la fuente falla con un
error claro en vez de devolver niveles mal colocados.
"""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from . import config as cfg
from .geo import paises
from .red import FuenteNoDisponible, FuenteOmitida, sesion
from .viento.aemet import BASE

NIVELES = ("Muy bajo", "Bajo", "Moderado", "Alto", "Muy alto", "Extremo")
# Colores propios del visor (no los de AEMET): misma escala, legibles sobre el relieve.
COLORES = ((70, 130, 200), (80, 190, 230), (90, 200, 70), (240, 220, 40), (240, 130, 20), (220, 30, 30))

TAMANO = (1525, 1017)                    # tamaño de la imagen de AEMET
CAJA = (25, 1249, 68, 991)               # x0, x1, y0, y1 del mapa dentro de la imagen
EXTENSION = (-10.516, 4.969, 34.977, 44.016)   # lon0, lon1, lat0, lat1 (centros de píxel de la caja)
# Superficie mínima para que un nivel cuente como "máximo de la zona": evita que
# unos píxeles de borde decidan el titular (1 píxel ≈ 1,2 km²).
PIXELES_MINIMOS = 10
# Cortes de tono (grados) entre niveles; leyenda medida: 210, 193, 103, 61, 33, 9.
_CORTES_TONO = ((21, 5), (47, 4), (82, 3), (150, 2), (201, 1), (265, 0))


def _merc(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


@lru_cache(maxsize=1)
def _mascara_espana():
    """Píxeles de la caja cuyo centro cae en España (o a ≤ 2 km de su costa)."""
    import numpy as np
    from matplotlib.path import Path as Trazado

    x0, x1, y0, y1 = CAJA
    lon0, lon1, lat0, lat1 = EXTENSION
    ys, xs = np.mgrid[0:y1 - y0 + 1, 0:x1 - x0 + 1]
    lon = lon0 + xs / (x1 - x0) * (lon1 - lon0)
    m = _merc(lat1) - ys / (y1 - y0) * (_merc(lat1) - _merc(lat0))
    lat = np.degrees(2 * np.arctan(np.exp(m)) - math.pi / 2)
    puntos = np.column_stack([lon.ravel(), lat.ravel()])
    dentro = np.zeros(len(puntos), dtype=bool)
    for _, poligono in paises()["ESP"]:
        dentro |= Trazado(poligono[0]).contains_points(puntos, radius=0.02)
    return dentro.reshape(lon.shape)


def _clasificar(png: bytes):
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.size != TAMANO:
        raise FuenteNoDisponible(f"AEMET cambió el formato del mapa de riesgo ({img.size} en vez de {TAMANO})")
    x0, x1, y0, y1 = CAJA
    a = np.asarray(img).astype(float)[y0:y1 + 1, x0:x1 + 1] / 255
    mx, mn = a.max(2), a.min(2)
    saturado = (mx - mn) > 0.23
    mar = (np.abs(a - np.array([173, 216, 230]) / 255).max(2) < 0.03)
    tono = np.zeros(mx.shape)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    d = np.where(mx - mn == 0, 1, mx - mn)
    tono = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    tono = np.where(tono >= 340, 0, tono)
    nivel = np.full(mx.shape, 255, dtype=np.uint8)
    # Solo España: fuera quedan el logo, el texto de copyright y los países vecinos.
    validos = saturado & ~mar & _mascara_espana()
    limite_inferior = 0
    for corte, n in _CORTES_TONO:
        nivel[validos & (tono >= limite_inferior) & (tono < corte)] = n
        limite_inferior = corte
    # Rellenar huecos finos (límites provinciales, texto) con la moda de la vecindad,
    # solo donde hay tierra coloreada alrededor.
    for _ in range(2):
        hueco = nivel == 255
        vecinos = np.stack([np.roll(np.roll(nivel, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
        cuenta = np.stack([(vecinos == k).sum(0) for k in range(6)])
        moda = cuenta.argmax(0).astype(np.uint8)
        relleno = hueco & (cuenta.max(0) >= 4) & _mascara_espana()
        nivel[relleno] = moda[relleno]
    return nivel


def _png_niveles(nivel) -> tuple[str, str]:
    """(capa de color semitransparente, raster de niveles en gris) como data URI."""
    import numpy as np
    from PIL import Image

    rgba = np.zeros(nivel.shape + (4,), dtype=np.uint8)
    for n, c in enumerate(COLORES):
        rgba[nivel == n] = (*c, 255)
    color, gris = io.BytesIO(), io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(color, "PNG", optimize=True)
    Image.fromarray(nivel, "L").save(gris, "PNG", optimize=True)
    uri = lambda b: "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    return uri(color), uri(gris)


def _limites():
    """Bordes exteriores de la caja (medio píxel más allá de los centros)."""
    lon0, lon1, lat0, lat1 = EXTENSION
    x0, x1, y0, y1 = CAJA
    medio_x = (lon1 - lon0) / (x1 - x0) / 2
    inv = lambda m: math.degrees(2 * math.atan(math.exp(m)) - math.pi / 2)
    medio_y = (_merc(lat1) - _merc(lat0)) / (y1 - y0) / 2
    return [[round(inv(_merc(lat0) - medio_y), 5), round(lon0 - medio_x, 5)],
            [round(inv(_merc(lat1) + medio_y), 5), round(lon1 + medio_x, 5)]]


async def obtener_prevision(dias=(1, 2, 3)) -> list[dict]:
    """Un elemento por día de previsión, con la capa lista para el visor."""
    import numpy as np

    if not cfg.AEMET_API_KEY:
        raise FuenteOmitida("falta AEMET_API_KEY")
    hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
    salida = []
    async with sesion() as s:
        for dia in dias:
            sobre = (await s.get(f"{BASE}/incendios/mapasriesgo/previsto/dia/{dia}/area/p",
                                 params={"api_key": cfg.AEMET_API_KEY})).json()
            if not sobre.get("datos"):
                raise FuenteNoDisponible(f"AEMET sin mapa de riesgo para el día {dia}: {sobre.get('descripcion')}")
            nivel = _clasificar((await s.get(sobre["datos"])).contenido)
            color, gris = _png_niveles(nivel)
            terrestres = nivel[nivel != 255]
            reparto = {NIVELES[n]: round(100 * float((terrestres == n).mean()), 1) for n in range(6)}
            presentes = [n for n in range(6) if (terrestres == n).sum() >= PIXELES_MINIMOS]
            salida.append({"dia": dia, "fecha": (hoy + timedelta(days=dia)).isoformat(),
                           "validez": "12:00 UTC", "limites": _limites(), "capa": color, "niveles": gris,
                           "reparto_pct": reparto, "nivel_max": NIVELES[max(presentes)] if presentes else None})
    return salida
