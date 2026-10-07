"""
Open-Meteo — viento actual (modelo, no observación) en cualquier coordenada.

Gratis, sin registro, y admite muchas coordenadas por petición. Se usa para dos
cosas:

* `obtener_rejilla()`: capa nacional de respaldo sobre las 52 capitales de
  provincia, para tener viento aunque no haya clave de AEMET.
* `viento_en_focos()`: capa de emergencia — el viento justo en cada foco
  satelital. Es lo más parecido al visor ALCIF de AEMET (que no tiene API
  pública): dato meteorológico centrado en el punto del incendio.

Ojo: es salida de modelo (resolución 1–11 km según zona), no una medida. Donde
haya estación AEMET cerca, la estación manda.
"""
from __future__ import annotations

from ..red import sesion
from . import lectura

URL = "https://api.open-meteo.com/v1/forecast"
POR_PETICION = 100
VARIABLES = "wind_speed_10m,wind_direction_10m,wind_gusts_10m,temperature_2m,relative_humidity_2m"

CAPITALES = (
    ("A Coruña", 43.362, -8.411), ("Lugo", 43.012, -7.556), ("Ourense", 42.336, -7.864),
    ("Pontevedra", 42.431, -8.644), ("Oviedo", 43.361, -5.849), ("Santander", 43.462, -3.810),
    ("Bilbao", 43.263, -2.935), ("San Sebastián", 43.318, -1.981), ("Vitoria", 42.846, -2.672),
    ("Pamplona", 42.812, -1.646), ("Logroño", 42.466, -2.445), ("Zaragoza", 41.649, -0.889),
    ("Huesca", 42.136, -0.408), ("Teruel", 40.345, -1.106), ("Barcelona", 41.385, 2.173),
    ("Girona", 41.979, 2.821), ("Lleida", 41.617, 0.620), ("Tarragona", 41.119, 1.245),
    ("Castellón", 39.986, -0.051), ("Valencia", 39.470, -0.376), ("Alicante", 38.345, -0.481),
    ("Murcia", 37.992, -1.131), ("Palma", 39.570, 2.650), ("León", 42.599, -5.567),
    ("Palencia", 42.010, -4.528), ("Burgos", 42.344, -3.697), ("Soria", 41.764, -2.468),
    ("Valladolid", 41.652, -4.724), ("Zamora", 41.503, -5.745), ("Salamanca", 40.970, -5.663),
    ("Segovia", 40.943, -4.109), ("Ávila", 40.656, -4.700), ("Madrid", 40.417, -3.704),
    ("Guadalajara", 40.633, -3.167), ("Cuenca", 40.070, -2.137), ("Toledo", 39.863, -4.027),
    ("Ciudad Real", 38.985, -3.927), ("Albacete", 38.994, -1.858), ("Cáceres", 39.475, -6.372),
    ("Badajoz", 38.879, -6.970), ("Huelva", 37.261, -6.945), ("Sevilla", 37.389, -5.984),
    ("Córdoba", 37.888, -4.779), ("Jaén", 37.779, -3.784), ("Granada", 37.177, -3.599),
    ("Almería", 36.834, -2.464), ("Málaga", 36.721, -4.421), ("Cádiz", 36.527, -6.289),
    ("Santa Cruz de Tenerife", 28.464, -16.252), ("Las Palmas de Gran Canaria", 28.124, -15.436),
    ("Ceuta", 35.889, -5.321), ("Melilla", 35.292, -2.938),
)


async def _consultar(puntos: list[tuple[str, float, float]]) -> list[dict]:
    async with sesion() as s:
        return [l for i in range(0, len(puntos), POR_PETICION)
                for l in await _lote(s, puntos[i:i + POR_PETICION])]


async def _lote(s, lote: list[tuple[str, float, float]]) -> list[dict]:
    datos = (await s.get(URL, params={
        "latitude": ",".join(f"{p[1]:.4f}" for p in lote),
        "longitude": ",".join(f"{p[2]:.4f}" for p in lote),
        "current": VARIABLES,
        "wind_speed_unit": "kmh",
        "timezone": "GMT",
    })).json()
    if isinstance(datos, dict):     # con una sola coordenada no viene lista
        datos = [datos]
    lecturas = []
    for (nombre, lat, lon), d in zip(lote, datos):
        c = d.get("current") or {}
        lecturas.append(lectura(
            fuente="Open-Meteo",
            id=f"{lat:.3f},{lon:.3f}",
            nombre=nombre,
            lat=lat,
            lon=lon,
            fecha_utc=f"{c['time']}:00+00:00" if c.get("time") else None,
            velocidad_kmh=c.get("wind_speed_10m"),
            racha_kmh=c.get("wind_gusts_10m"),
            direccion_grados=c.get("wind_direction_10m"),
            temperatura_c=c.get("temperature_2m"),
            humedad_pct=c.get("relative_humidity_2m"),
        ))
    return lecturas


async def obtener_rejilla() -> list[dict]:
    return await _consultar(list(CAPITALES))


async def viento_en_focos(focos: list[dict], celda_grados: float = 0.1,
                          max_puntos: int = 400) -> dict[tuple[float, float], dict]:
    """
    Viento en la celda (~10 km) de cada foco. Varios focos de un mismo incendio
    caen en la misma celda y comparten consulta. Devuelve {celda: lectura};
    `celda_de()` da la celda de un foco.
    """
    celdas = sorted({celda_de(f, celda_grados) for f in focos})[:max_puntos]
    lecturas = await _consultar([(None, lat, lon) for lat, lon in celdas])
    return dict(zip(celdas, lecturas))


def celda_de(foco: dict, celda_grados: float = 0.1) -> tuple[float, float]:
    redondeo = lambda v: round(round(v / celda_grados) * celda_grados, 4)
    return redondeo(foco["lat"]), redondeo(foco["lon"])
