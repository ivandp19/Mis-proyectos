"""
Viento: un único esquema para todas las fuentes.

Dirección: `direccion_grados` es de DÓNDE viene el viento (convención
meteorológica, la que dan AEMET y Open-Meteo). Para incendios interesa hacia
dónde empuja el fuego, así que se añade `hacia_grados` (= +180°).

Antigüedad: no se descarta ninguna estación por tener la lectura atrasada (en
una zona sin otra estación, un dato de hace 3 h sigue sirviendo). Cada lectura
lleva `antiguedad_min` para que quien la use decida cuánto fiarse.
"""
from __future__ import annotations

from datetime import datetime, timezone

_CARDINALES = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO")


def cardinal(grados: float | None) -> str | None:
    if grados is None:
        return None
    return _CARDINALES[int((grados % 360) / 22.5 + 0.5) % 16]


def regla_30(temperatura_c, humedad_pct, velocidad_kmh) -> bool | None:
    """
    Regla del 30: >30 °C, <30 % de humedad y viento >30 km/h. Es el umbral de
    condiciones extremas de propagación que usan los servicios de extinción;
    aquí es un indicador, no un índice de riesgo calibrado.
    """
    if None in (temperatura_c, humedad_pct, velocidad_kmh):
        return None
    return temperatura_c > 30 and humedad_pct < 30 and velocidad_kmh > 30


def _antiguedad_min(fecha_utc: str | None) -> int | None:
    if not fecha_utc:
        return None
    return max(0, round((datetime.now(timezone.utc) - datetime.fromisoformat(fecha_utc)).total_seconds() / 60))


def lectura(*, fuente: str, id: str, nombre: str | None, lat: float, lon: float,
            fecha_utc: str | None, velocidad_kmh, racha_kmh, direccion_grados,
            temperatura_c=None, humedad_pct=None) -> dict:
    r = lambda v: None if v is None else round(float(v), 1)
    vel, racha, dirg = r(velocidad_kmh), r(racha_kmh), r(direccion_grados)
    temp, hum = r(temperatura_c), r(humedad_pct)
    return {
        "fuente": fuente,
        "id": id,
        "nombre": nombre,
        "lat": lat,
        "lon": lon,
        "fecha_utc": fecha_utc,
        "velocidad_kmh": vel,
        "racha_kmh": racha,
        "direccion_grados": dirg,
        "direccion_cardinal": cardinal(dirg),
        "hacia_grados": None if dirg is None else (dirg + 180) % 360,
        "antiguedad_min": _antiguedad_min(fecha_utc),
        "temperatura_c": temp,
        "humedad_pct": hum,
        "regla_30": regla_30(temp, hum, vel),
    }
