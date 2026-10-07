"""
Cobertura del suelo en un punto — ESA WorldCover 2021 (10 m), resumida a ≈ 90 m.

Responde a "¿qué hay donde ha saltado este foco?": bosque, matorral, pasto,
cultivo, urbano, agua… Sirve para tres cosas:

* separar incendios forestales probables de quemas agrícolas, fuentes urbanas o
  industriales y falsos positivos sobre agua;
* decidir si tiene sentido dibujar la propagación (solo con combustible natural);
* dar contexto en las fichas del visor.

Limitación conocida de WorldCover en el Mediterráneo: los cultivos leñosos se
confunden con vegetación natural (comprobado: olivar de Jaén → "bosque", viñedo
de La Mancha → "matorral"/"pasto"), y en 2021 varios embalses bajos salen como
"pasto". "Cultivo" es fiable sobre todo para cereal y regadío.

Los datos son locales (`datos/cobertura_*.tif`, generados una vez con
`herramientas/generar_cobertura.py`): no hay ninguna petición de red. Si no se
han generado, la fuente queda `omitida` y el resto del pipeline sigue.

Para cada punto se mira una ventana del tamaño del píxel del satélite (un foco
VIIRS representa ~375 m, MODIS ~1 km), no solo la celda central: un foco al
borde de un pinar y un cultivo tiene ambas cosas dentro.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .red import FuenteOmitida

DATOS = Path(__file__).resolve().parent / "datos"
CLASES = {10: "bosque", 20: "matorral", 30: "pasto", 40: "cultivo", 50: "urbano", 60: "suelo desnudo",
          70: "nieve", 80: "agua", 90: "humedal", 95: "manglar", 100: "musgo y liquen"}
COMBUSTIBLE = {10, 20, 30}          # vegetación natural que propaga un incendio forestal
_M_POR_GRADO = 111_320


@lru_cache(maxsize=1)
def _zonas() -> dict:
    meta = DATOS / "cobertura.json"
    if not meta.exists():
        raise FuenteOmitida("falta la cobertura del suelo: ejecuta herramientas/generar_cobertura.py una vez")
    import rasterio

    zonas = {}
    for nombre, fichero in json.loads(meta.read_text(encoding="utf-8"))["zonas"].items():
        ds = rasterio.open(DATOS / fichero)
        zonas[nombre] = ds
    return zonas


def disponible() -> bool:
    try:
        _zonas()
        return True
    except FuenteOmitida:
        return False


def en_punto(lat: float, lon: float, radio_m: float = 200) -> dict | None:
    """
    Reparto de coberturas en un cuadrado de lado 2·radio_m centrado en el punto.
    None si el punto cae fuera de España o sin dato.
    """
    from rasterio.windows import Window

    for ds in _zonas().values():
        b = ds.bounds
        if not (b.left <= lon <= b.right and b.bottom <= lat <= b.top):
            continue
        celda_grados = ds.res[0]
        fila, col = ds.index(lon, lat)
        rf = max(0, math.ceil(radio_m / (celda_grados * _M_POR_GRADO)))
        rc = max(0, math.ceil(radio_m / (celda_grados * _M_POR_GRADO * math.cos(math.radians(lat)))))
        ventana = Window(col - rc, fila - rf, 2 * rc + 1, 2 * rf + 1)
        valores = ds.read(1, window=ventana, boundless=True, fill_value=0).ravel()
        valores = valores[valores != 0]
        if not valores.size:
            return None
        por_valor = {int(v): int((valores == v).sum()) for v in set(valores.tolist())}
        total = sum(por_valor.values())
        fracciones = {CLASES.get(v, str(v)): round(100 * n / total)
                      for v, n in sorted(por_valor.items(), key=lambda x: -x[1])}
        combustible = sum(n for v, n in por_valor.items() if v in COMBUSTIBLE)
        return {"dominante": next(iter(fracciones)), "fracciones_pct": fracciones,
                "combustible_pct": round(100 * combustible / total), "radio_m": round(radio_m)}
    return None


def radio_para(registro: dict) -> float:
    """Ventana del tamaño del píxel del satélite (mitad de su resolución), mínimo 200 m."""
    return max(200, (registro.get("resolucion_m") or 400) / 2)


def anotar(*listas: list[dict]) -> list[dict]:
    """
    Añade `cobertura` a cada registro (focos, incidencias…) con lat/lon. Devuelve
    la lista de registros anotados, para que `pipeline.ejecutar` la cuente.
    Lanza FuenteOmitida si los datos no se han generado.
    """
    _zonas()
    anotados = []
    for lista in listas:
        for r in lista:
            r["cobertura"] = en_punto(r["lat"], r["lon"], radio_para(r))
            if r["cobertura"]:
                anotados.append(r)
    return anotados


NOMBRE_FUENTE = "Cobertura del suelo (ESA WorldCover)"


async def anotar_async(*listas: list[dict]) -> list[dict]:
    """Versión para `pipeline.ejecutar`, que espera una corrutina (el trabajo es local y síncrono)."""
    return anotar(*listas)


# --- Capa para el visor ------------------------------------------------------------------
# Colores oficiales de la leyenda de ESA WorldCover (reconocibles para quien conozca el producto).
COLORES = {10: (0, 100, 0), 20: (255, 187, 34), 30: (255, 255, 76), 40: (240, 150, 255), 50: (250, 0, 0),
           60: (180, 180, 180), 70: (240, 240, 240), 80: (0, 100, 200), 90: (0, 150, 160), 95: (0, 207, 117),
           100: (250, 230, 160)}
REDUCCION = 4          # 4 × 4 celdas de ≈ 90 m → ≈ 370 m por píxel de la capa


def _merc(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _capa_zona(ds):
    """
    Rejilla de la zona → imagen RGBA lista para Leaflet: cobertura dominante en
    bloques de 4 × 4 y filas reproyectadas a Mercator. La rejilla original va en
    grados con filas equiespaciadas en latitud; Leaflet estira la imagen en
    Mercator, así que sin este paso la capa se desplazaría hacia norte y sur.
    """
    import numpy as np

    a = ds.read(1)
    h, w = a.shape[0] // REDUCCION, a.shape[1] // REDUCCION
    bloques = a[:h * REDUCCION, :w * REDUCCION].reshape(h, REDUCCION, w, REDUCCION)
    valores = np.array(sorted(COLORES), dtype=np.uint8)
    cuenta = np.stack([(bloques == v).sum(axis=(1, 3), dtype=np.uint8) for v in valores])
    reducida = valores[cuenta.argmax(axis=0)]
    reducida[cuenta.max(axis=0) == 0] = 0

    b = ds.bounds
    norte, sur = b.top, b.top - h * REDUCCION * ds.res[1]
    este = b.left + w * REDUCCION * ds.res[0]
    m_n, m_s = _merc(norte), _merc(sur)
    filas = (np.arange(h) + 0.5) / h * (m_n - m_s)
    lat = np.degrees(2 * np.arctan(np.exp(m_n - filas)) - math.pi / 2)
    origen = np.clip(((norte - lat) / (norte - sur) * h).astype(int), 0, h - 1)
    reproyectada = reducida[origen]

    rgba = np.zeros(reproyectada.shape + (4,), dtype=np.uint8)
    for v, c in COLORES.items():
        rgba[reproyectada == v] = (*c, 255)
    return rgba, [[round(sur, 6), round(b.left, 6)], [round(norte, 6), round(este, 6)]]


def capa_visor() -> dict | None:
    """
    {"zonas": {nombre: {"png": data URI, "limites": [[S,O],[N,E]]}}, "clases": {...}} para el
    visor, o None si los datos no se han generado. Las imágenes se calculan una vez y se
    guardan junto a las rejillas (`cobertura_capa_*.png`); se rehacen si la rejilla cambia.
    """
    import base64

    try:
        zonas = _zonas()
    except FuenteOmitida:
        return None
    from PIL import Image

    salida = {}
    for nombre, ds in zonas.items():
        png, meta = DATOS / f"cobertura_capa_{nombre}.png", DATOS / f"cobertura_capa_{nombre}.json"
        origen = Path(ds.name)
        if not (png.exists() and meta.exists() and png.stat().st_mtime >= origen.stat().st_mtime):
            rgba, limites = _capa_zona(ds)
            Image.fromarray(rgba, "RGBA").save(png, optimize=True)
            meta.write_text(json.dumps({"limites": limites}), encoding="utf-8")
        salida[nombre] = {"png": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode(),
                          "limites": json.loads(meta.read_text(encoding="utf-8"))["limites"]}
    presentes = {CLASES[v]: "#%02x%02x%02x" % COLORES[v] for v in (10, 20, 30, 40, 50, 60, 80, 90)}
    return {"zonas": salida, "clases": presentes,
            "fuente": "ESA WorldCover 2021 (10 m, CC BY 4.0), cobertura dominante en celdas de ≈ 370 m"}
