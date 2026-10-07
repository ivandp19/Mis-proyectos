"""
EUMETSAT LSA-SAF — FRP-PIXEL de Meteosat SEVIRI (geoestacionario, cada 15 min).

Complementa a FIRMS: menos resolución (~3–5 km sobre España) pero ve España de
forma continua, así que detecta incendios entre pasadas de VIIRS/MODIS.

Acceso: el listado de directorios es público pero los ficheros piden usuario
(registro gratuito, ver `config.py`). Sin credenciales la fuente se OMITE.

Cada 15 min hay dos ficheros; el que trae los focos es `FRP-PIXEL-ListProduct`
(una fila por píxel con fuego para todo el disco MSG: Europa + África), y aquí
se recorta a España.

Formato (verificado con ficheros reales el 2026-10-06, `diagnosticar()`): un
dataset 1-D por variable en la raíz del HDF5, enteros con atributos
`SCALING_FACTOR` (LATITUDE/LONGITUDE ×100, FRP ×10, FIRE_CONFIDENCE ×100) y
`MISSING_VALUE` (19000 en coordenadas, -999 en el resto). `ACQTIME` es la hora
HHMM UTC de adquisición de cada píxel: SEVIRI barre el disco de sur a norte en
~12 min, así que es más precisa que la hora del fichero.
"""
from __future__ import annotations

import asyncio
import base64
import bz2
import io
import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from .. import config as cfg
from ..geo import en_espana, paises
from ..red import FuenteNoDisponible, FuenteOmitida, sesion

BASE = "https://datalsasaf.lsasvcs.ipma.pt"
RUTA_DIA = "/PRODUCTS/MSG/FRP-PIXEL/HDF5/{:%Y/%m/%d}/"
_FICHERO = re.compile(r'href="(/PRODUCTS/[^"]+FRP-PIXEL-ListProduct[^"]*_(\d{12})[^"]*)"')

_NOMBRES = {
    "lat": ("LATITUDE", "Latitude", "LAT"),
    "lon": ("LONGITUDE", "Longitude", "LON"),
    "frp": ("FRP", "FRP_MW"),
    "confianza": ("FIRE_CONFIDENCE", "CONFIDENCE"),
    "hora": ("ACQTIME",),
}


async def _ficheros_recientes(s, horas: float) -> list[tuple[datetime, str]]:
    ahora = datetime.now(timezone.utc)
    limite = ahora - timedelta(hours=horas)
    encontrados = []
    dia = limite.date()
    while dia <= ahora.date():
        html = (await s.get(BASE + RUTA_DIA.format(dia))).texto
        for ruta, stamp in _FICHERO.findall(html):
            fecha = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            if fecha >= limite:
                encontrados.append((fecha, ruta))
        dia += timedelta(days=1)
    return sorted(set(encontrados))


def _dataset(h5, clave: str):
    for nombre in _NOMBRES[clave]:
        if nombre in h5:
            ds = h5[nombre]
            valores = ds[()].astype(float).ravel()
            if "MISSING_VALUE" in ds.attrs:
                valores[valores == float(ds.attrs["MISSING_VALUE"])] = math.nan
            return valores / float(ds.attrs.get("SCALING_FACTOR", 1) or 1)
    if clave in ("lat", "lon"):
        raise FuenteNoDisponible(f"FRP-PIXEL sin dataset {clave}; trae: {list(h5.keys())}")
    return None


def _hora_pixel(fecha_fichero: datetime, hhmm) -> datetime:
    """Hora de adquisición del píxel (ACQTIME, HHMM) o, si falta, la del fichero."""
    if hhmm is None or math.isnan(hhmm):
        return fecha_fichero
    h, m = divmod(int(hhmm), 100)
    fecha = fecha_fichero.replace(hour=h, minute=m)
    # El fichero de las 23:45 puede traer píxeles adquiridos a las 00:0x.
    return fecha + timedelta(days=1) if fecha < fecha_fichero - timedelta(hours=12) else fecha


def _leer(contenido: bytes, fecha: datetime) -> list[dict]:
    import h5py  # dependencia solo de esta fuente
    import numpy as np

    if contenido[:3] == b"BZh":
        contenido = bz2.decompress(contenido)
    if contenido[:4] != b"\x89HDF":
        raise FuenteNoDisponible(f"FRP-PIXEL no es HDF5 (empieza por {contenido[:16]!r})")
    with h5py.File(io.BytesIO(contenido), "r") as h5:
        lats, lons = _dataset(h5, "lat"), _dataset(h5, "lon")
        frps, confs, horas = _dataset(h5, "frp"), _dataset(h5, "confianza"), _dataset(h5, "hora")
    if len(lats) and (np.nanmax(abs(lats), initial=0) > 90 or np.nanmax(abs(lons), initial=0) > 180):
        # Escala mal leída: sin esta comprobación ningún foco caería en España
        # y el resultado sería un 0 silencioso, indistinguible de "no hay fuego".
        raise FuenteNoDisponible(f"FRP-PIXEL: coordenadas fuera de rango (lat máx {np.nanmax(abs(lats))}, "
                                 f"lon máx {np.nanmax(abs(lons))}): factor de escala mal leído")
    focos = []
    for i, (lat, lon) in enumerate(zip(lats, lons)):
        if math.isnan(lat) or math.isnan(lon) or not en_espana(float(lat), float(lon)):
            continue
        conf = None if confs is None or math.isnan(confs[i]) else float(confs[i])
        frp = None if frps is None or math.isnan(frps[i]) else round(float(frps[i]), 2)
        focos.append({
            "fuente": "EUMETSAT LSA-SAF",
            "sensor": "SEVIRI",
            "satelite": "Meteosat MSG",
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "fecha_utc": _hora_pixel(fecha, None if horas is None else horas[i]).isoformat(),
            "confianza": None if conf is None else "alta" if conf >= 0.8 else "media" if conf >= 0.5 else "baja",
            "confianza_bruta": conf,
            "frp_mw": frp,
            "dia_noche": None,
            "resolucion_m": 3000,
        })
    return focos


def _sesion_autenticada():
    if not (cfg.LSASAF_USER and cfg.LSASAF_PASSWORD):
        raise FuenteOmitida("faltan LSASAF_USER / LSASAF_PASSWORD")
    credencial = base64.b64encode(f"{cfg.LSASAF_USER}:{cfg.LSASAF_PASSWORD}".encode()).decode()
    return sesion(headers={"Authorization": f"Basic {credencial}"})


async def obtener_focos(horas: float = 3, max_ficheros: int = 24) -> list[dict]:
    """
    Focos SEVIRI de las últimas `horas`. Por defecto 3 h (12 ficheros): para la
    visión de 24 h ya está FIRMS; SEVIRI aporta sobre todo lo más reciente.
    `max_ficheros` evita descargar cientos de ficheros por un `horas` grande.
    """
    focos = []
    async with _sesion_autenticada() as s:
        for fecha, ruta in (await _ficheros_recientes(s, horas))[-max_ficheros:]:
            focos.extend(_leer((await s.get(BASE + ruta)).contenido, fecha))
            await asyncio.sleep(0.5)
    return focos


async def diagnosticar() -> dict:
    """
    Abre el fichero FRP-PIXEL más reciente y cuenta qué trae, sin filtrar:
    datasets y sus atributos, cuántos píxeles de fuego hay en todo el disco
    (Europa + África: casi nunca es 0), rango de coordenadas y cuántos caen
    en España. Sirve para distinguir "no hay fuego en España" de "se lee mal".
    """
    import h5py
    import numpy as np

    async with _sesion_autenticada() as s:
        fecha, ruta = (await _ficheros_recientes(s, horas=1))[-1]
        contenido = (await s.get(BASE + ruta)).contenido
    if contenido[:3] == b"BZh":
        contenido = bz2.decompress(contenido)
    informe = {"fichero": ruta.rsplit("/", 1)[-1], "bytes": len(contenido), "datasets": {}}
    with h5py.File(io.BytesIO(contenido), "r") as h5:
        informe["atributos_raiz"] = {k: str(v)[:80] for k, v in list(h5.attrs.items())[:15]}

        def visitar(nombre, obj):
            if isinstance(obj, h5py.Dataset):
                datos = obj[()]
                informe["datasets"][nombre] = {
                    "forma": list(obj.shape), "tipo": str(obj.dtype),
                    "atributos": {k: str(v)[:60] for k, v in obj.attrs.items()},
                    "primeros": [x.item() if hasattr(x, "item") else str(x) for x in np.ravel(datos)[:3]],
                }
        h5.visititems(visitar)
        lats, lons = _dataset(h5, "lat"), _dataset(h5, "lon")
    validos = ~(np.isnan(lats) | np.isnan(lons))
    informe["pixeles_fuego_disco_completo"] = int(len(lats))
    informe["pixeles_sin_coordenadas"] = int((~validos).sum())
    lats, lons = lats[validos], lons[validos]
    if len(lats):
        informe["lat_rango"] = [round(float(lats.min()), 3), round(float(lats.max()), 3)]
        informe["lon_rango"] = [round(float(lons.min()), 3), round(float(lons.max()), 3)]
        informe["en_caja_iberica"] = int(((lats > 27) & (lats < 44.5) & (lons > -19) & (lons < 5.5)).sum())
        informe["en_espana"] = sum(en_espana(float(a), float(o)) for a, o in zip(lats, lons))
    return informe


# --- Vigilancia: ¿qué parte de España pudo mirar SEVIRI? -----------------------
#
# "0 focos" no significa "no hay fuego" si España estaba nublada: SEVIRI no
# busca fuego bajo nube (comprobado: el 2026-10-05 a las 15:15 UTC un incendio
# de ~650 MW en Badajoz visto por MODIS cayó en píxeles clase 3 = nube). El
# `QualityProduct` (0,7 MB, gzip) clasifica cada píxel del disco; aquí se cuenta
# esa clasificación sobre los píxeles de España.
#
# Clases: Tabla S1 del suplemento de Wooster et al. (2015), ACP 15, 13217.
_CLASES_VIGILADO = {0, 1, 2, 5, 6, 7}     # se intentó detectar fuego
_CLASES_NUBE = {3, 8}                      # nube / borde de nube
# 4 sun glint, 9 entrada corrupta, 10 agua, 11 borde de agua, 254 no procesado
# (urbano…), 255 fuera del disco: no vigilado por otros motivos.

# Proyección geoestacionaria del disco MSG (3712×3712, satélite en 0°). Ajustada
# con las ABS_LINE/ABS_PIXEL reales de 653 focos: error máximo 0,5 píxeles.
_COFF = _LOFF = 1857
_PIXELES_POR_GRADO = 13642337 * 2 ** -16


def _latlon_de_pixel(lineas, columnas):
    """Inversa de la proyección geoestacionaria (CGMS LRIT/HRIT, satélite en 0°)."""
    import numpy as np

    x = np.radians((columnas - _COFF) / _PIXELES_POR_GRADO)
    y = np.radians((lineas - _LOFF) / _PIXELES_POR_GRADO)
    cx, cy, sx, sy = np.cos(x), np.cos(y), np.sin(x), np.sin(y)
    k = cy ** 2 + 1.006739501 * sy ** 2
    sa = (42164 * cx * cy) ** 2 - k * 1737122264
    with np.errstate(invalid="ignore"):
        sn = (42164 * cx * cy - np.sqrt(sa)) / k
    s1, s2, s3 = 42164 - sn * cx * cy, sn * sx * cy, -sn * sy
    lat = np.degrees(np.arctan(1.006739501 * s3 / np.hypot(s1, s2)))
    lon = np.degrees(np.arctan(s2 / s1))
    return lat, lon


@lru_cache(maxsize=1)
def _pixeles_espana():
    """(líneas, columnas) de los píxeles SEVIRI cuyo centro cae en España."""
    import numpy as np
    from matplotlib.path import Path as Trazado

    lineas, columnas = np.mgrid[480:800, 1350:1950]      # cubre península, Baleares y Canarias
    lat, lon = _latlon_de_pixel(lineas.astype(float), columnas.astype(float))
    puntos = np.column_stack([lon.ravel(), lat.ravel()])
    dentro = np.zeros(len(puntos), dtype=bool)
    for _, poligono in paises()["ESP"]:
        dentro |= Trazado(poligono[0]).contains_points(np.nan_to_num(puntos, nan=999))
    return lineas.ravel()[dentro], columnas.ravel()[dentro]


def _vigilancia(contenido: bytes) -> dict:
    import h5py

    with h5py.File(io.BytesIO(contenido), "r") as h5:
        clases = h5["QUALITYFLAG"][()][_pixeles_espana()]
    total = len(clases)
    vigilado = sum(int((clases == c).sum()) for c in _CLASES_VIGILADO)
    nube = sum(int((clases == c).sum()) for c in _CLASES_NUBE)
    return {"pixeles_espana": total,
            "pct_vigilado": round(100 * vigilado / total, 1),
            "pct_nubes": round(100 * nube / total, 1),
            "pct_otros": round(100 * (total - vigilado - nube) / total, 1)}


async def vigilancia_espana() -> dict:
    """
    Qué porcentaje de España pudo vigilar SEVIRI en el fichero más reciente.
    Con `pct_vigilado` bajo, "0 focos" significa "no se pudo mirar", no "no hay fuego".
    """
    async with _sesion_autenticada() as s:
        fecha, ruta = (await _ficheros_recientes(s, horas=1))[-1]
        ruta = ruta.replace("FRP-PIXEL-ListProduct", "FRP-PIXEL-QualityProduct")
        return {"fecha_utc": fecha.isoformat(), **_vigilancia((await s.get(BASE + ruta)).contenido)}
