"""
AEMET OpenData — observación convencional de TODAS las estaciones automáticas.

Capa nacional: ~855 estaciones (≈750 con anemómetro) con velocidad (`vv`),
dirección (`dv`), racha máxima (`vmax`) y su dirección (`dmax`), más
temperatura y humedad. El endpoint
devuelve las últimas 24 h, hora a hora; aquí se queda la lectura más reciente
de cada estación.

Funciona en dos pasos, como toda la API de AEMET: la primera petición devuelve
un sobre con una URL temporal en `datos`, y esa URL trae el JSON real.

Unidades: AEMET da el viento en m/s; se pasa a km/h.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .. import config as cfg
from ..red import FuenteNoDisponible, FuenteOmitida, sesion
from . import lectura

BASE = "https://opendata.aemet.es/opendata/api"
MS_A_KMH = 3.6


def _utc(fint: str) -> str:
    # `fint` llega como "2026-10-05T15:00:00" (UTC) o con "+0000".
    fecha = datetime.fromisoformat(fint)
    return (fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)).isoformat()


def _nombre(ubi: str | None) -> str | None:
    """AEMET separa municipio y paraje con dos espacios: "EL BOSQUE  SAN JOSÉ"."""
    if not ubi:
        return ubi
    return " · ".join(p for p in re.split(r"\s{2,}", ubi.strip()) if p)


def _kmh(v):
    return None if v is None else float(v) * MS_A_KMH


async def obtener_estaciones() -> list[dict]:
    if not cfg.AEMET_API_KEY:
        raise FuenteOmitida("falta AEMET_API_KEY")
    async with sesion() as s:
        respuesta = await s.get(f"{BASE}/observacion/convencional/todas",
                                params={"api_key": cfg.AEMET_API_KEY})
        try:
            sobre = respuesta.json()
        except ValueError:
            # Con clave inválida AEMET puede responder 200 con cuerpo vacío.
            raise FuenteNoDisponible(f"AEMET no devolvió JSON: {respuesta.texto[:120]!r}")
        if not isinstance(sobre, dict) or not sobre.get("datos"):
            raise FuenteNoDisponible(f"AEMET sin 'datos': {sobre}")
        observaciones = (await s.get(sobre["datos"])).json()

    ultima: dict[str, dict] = {}
    for o in observaciones:
        if o.get("idema") and (o["idema"] not in ultima or o["fint"] > ultima[o["idema"]]["fint"]):
            ultima[o["idema"]] = o

    lecturas = []
    for o in ultima.values():
        # Las ~100 estaciones sin anemómetro se quedan: su temperatura y humedad
        # cuentan igual para el riesgo de incendio (viento a None, sin flecha).
        lecturas.append(lectura(
            fuente="AEMET",
            id=o["idema"],
            nombre=_nombre(o.get("ubi")),
            lat=float(o["lat"]),
            lon=float(o["lon"]),
            fecha_utc=_utc(o["fint"]),
            velocidad_kmh=_kmh(o.get("vv")),
            racha_kmh=_kmh(o.get("vmax")),
            direccion_grados=o.get("dv"),
            temperatura_c=o.get("ta"),
            humedad_pct=o.get("hr"),
        ))
    return lecturas
