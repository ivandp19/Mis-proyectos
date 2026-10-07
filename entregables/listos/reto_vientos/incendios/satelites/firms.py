"""
NASA FIRMS — focos de calor de VIIRS (375 m) y MODIS (1 km).

Dos modos, elegidos solos según haya o no `FIRMS_MAP_KEY`:

* SIN CLAVE: los CSV públicos de la región Europa (ventanas 24h / 48h / 7d).
  Pesan poco (≈200 KB/24h por satélite) y se recortan a España aquí.
* CON CLAVE: la API de área, que ya devuelve solo la caja pedida.

Pasadas: VIIRS y MODIS van en órbita polar, así que cada satélite pasa sobre la
Península un par de veces al día. Entre pasadas el dato puede tener 1–2 h de
retraso; para cubrir esos huecos está SEVIRI (`lsasaf.py`), geoestacionario.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from .. import config as cfg
from ..geo import en_espana
from ..red import sesion

BASE = "https://firms.modaps.eosdis.nasa.gov"

# (fuente API con clave, ruta CSV pública sin clave, sensor, resolución en m)
PRODUCTOS = (
    ("VIIRS_SNPP_NRT", "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Europe_{v}.csv", "VIIRS", 375),
    ("VIIRS_NOAA20_NRT", "noaa-20-viirs-c2/csv/J1_VIIRS_C2_Europe_{v}.csv", "VIIRS", 375),
    ("VIIRS_NOAA21_NRT", "noaa-21-viirs-c2/csv/J2_VIIRS_C2_Europe_{v}.csv", "VIIRS", 375),
    ("MODIS_NRT", "modis-c6.1/csv/MODIS_C6_1_Europe_{v}.csv", "MODIS", 1000),
)

SATELITES = {"N": "Suomi NPP", "N20": "NOAA-20", "1": "NOAA-20",
             "N21": "NOAA-21", "2": "NOAA-21", "A": "Aqua", "T": "Terra"}

# VIIRS da la confianza como categoría; MODIS como 0–100. Se unifican con los
# mismos cortes para MODIS que usa FIRMS en su visor (≥80 alta, 50–79 media).
_CONF_VIIRS = {"h": "alta", "high": "alta", "n": "media", "nominal": "media",
               "l": "baja", "low": "baja"}


def _confianza(bruta: str) -> str | None:
    bruta = (bruta or "").strip().lower()
    if bruta in _CONF_VIIRS:
        return _CONF_VIIRS[bruta]
    try:
        n = float(bruta)
    except ValueError:
        return None
    return "alta" if n >= 80 else "media" if n >= 50 else "baja"


def _ventana_publica(horas: int) -> str:
    return "24h" if horas <= 24 else "48h" if horas <= 48 else "7d"


def _bbox_api(bbox) -> str:
    return ",".join(str(x) for x in bbox)


def _filas(texto: str) -> list[dict]:
    texto = texto.strip()
    if not texto or not texto.startswith("latitude"):
        # La API de área responde texto plano ("Invalid MAP_KEY.") en errores.
        raise RuntimeError(f"FIRMS no devolvió CSV: {texto[:120]!r}")
    return list(csv.DictReader(io.StringIO(texto)))


def _normalizar(fila: dict, sensor: str, resolucion: int) -> dict:
    hhmm = fila["acq_time"].zfill(4)
    fecha = datetime.strptime(f"{fila['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    bruta = fila.get("confidence", "")
    return {
        "fuente": "NASA FIRMS",
        "sensor": sensor,
        "satelite": SATELITES.get(fila.get("satellite", ""), fila.get("satellite")),
        "lat": float(fila["latitude"]),
        "lon": float(fila["longitude"]),
        "fecha_utc": fecha.isoformat(),
        "confianza": _confianza(bruta),
        "confianza_bruta": bruta,
        "frp_mw": float(fila["frp"]) if fila.get("frp") else None,
        "dia_noche": {"D": "dia", "N": "noche"}.get(fila.get("daynight"), fila.get("daynight")),
        "resolucion_m": resolucion,
    }


async def obtener_focos(horas: int = 24) -> list[dict]:
    """Focos de los cuatro productos FIRMS en España en las últimas `horas`."""
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    focos: list[dict] = []
    async with sesion() as s:
        for fuente_api, ruta_publica, sensor, resolucion in PRODUCTOS:
            if cfg.FIRMS_MAP_KEY:
                # La API de área admite 1–5 días; se pide de más y se recorta abajo.
                dias = min(max(1, -(-horas // 24)), 5)
                urls = [f"{BASE}/api/area/csv/{cfg.FIRMS_MAP_KEY}/{fuente_api}/{_bbox_api(b)}/{dias}"
                        for b in cfg.BBOXES_ESPANA]
            else:
                urls = [f"{BASE}/data/active_fire/" + ruta_publica.format(v=_ventana_publica(horas))]
            for url in urls:
                for fila in _filas((await s.get(url)).texto):
                    foco = _normalizar(fila, sensor, resolucion)
                    if datetime.fromisoformat(foco["fecha_utc"]) >= limite and \
                            en_espana(foco["lat"], foco["lon"]):
                        focos.append(foco)
    return focos
