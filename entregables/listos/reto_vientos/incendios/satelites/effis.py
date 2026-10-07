"""
EFFIS (Copernicus) — áreas quemadas cartografiadas con MODIS y Sentinel-2.

No es detección de focos: son perímetros de lo ya quemado, con superficie (ha),
provincia, municipio y reparto por tipo de cubierta. Llega con días de retraso
respecto a FIRMS, pero es la cifra de referencia europea.

API REST pública, sin clave. No acepta filtro por fecha, así que se pide
ordenado y se pagina hasta pasar del límite.

Ventana por `lastupdate`, no por `firedate`: EFFIS cartografía con días de
retraso y sigue corrigiendo perímetros después (el 2026-10-05 actualizó 17
áreas de incendios del 21–28/9). Filtrando por fecha del incendio, una ventana
de 7 días salía vacía aunque EFFIS hubiera publicado 27 áreas esa semana. Como
`lastupdate` ≥ fecha de alta, este criterio recoge también las nuevas; cada área
lleva `novedad`: "nueva" (el incendio cae en la ventana) o "actualizada".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..red import sesion

URL = "https://api.effis.emergency.copernicus.eu/rest/2/burntareas/current/"
POR_PAGINA = 100
MAX_PAGINAS = 20

_CUBIERTAS = ("broadlea", "conifer", "mixed", "scleroph", "transit",
              "othernatlc", "agriareas", "artifsurf", "otherlc")


def _num(v):
    return None if v in (None, "") else float(v)


async def obtener_areas(dias: int = 7) -> list[dict]:
    """Áreas quemadas en España publicadas o actualizadas por EFFIS en los últimos `dias`."""
    async with sesion() as s:
        return await _paginar(s, datetime.now(timezone.utc) - timedelta(days=dias))


async def _paginar(s, limite: datetime) -> list[dict]:
    areas = []
    for pagina in range(MAX_PAGINAS):
        datos = (await s.get(URL, params={"country": "ES", "ordering": "-lastupdate",
                                          "limit": POR_PAGINA, "offset": pagina * POR_PAGINA})).json()
        for r in datos.get("results", []):
            if datetime.fromisoformat(r["lastupdate"]) < limite:
                return areas
            lon, lat = r["centroid"]["coordinates"]
            areas.append({
                "fuente": "EFFIS",
                "id_effis": r["id"],
                "lat": lat,
                "lon": lon,
                "fecha_incendio": r["firedate"],
                "novedad": "nueva" if datetime.fromisoformat(r["firedate"]) >= limite else "actualizada",
                "ultima_actualizacion": r.get("lastupdate"),
                "provincia": r.get("province"),
                "municipio": r.get("commune"),
                "area_ha": _num(r.get("area_ha")),
                "pct_natura2000": _num(r.get("percna2k")),
                "cubierta_pct": {k: _num(r.get(k)) for k in _CUBIERTAS},
                "geometria": r.get("shape"),
            })
        if not datos.get("next"):
            break
    return areas
