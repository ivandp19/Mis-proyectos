"""
Puertos del Estado (PORTUS, la red detrás de la app iMar) — viento en tiempo
real en boyas, mareógrafos y estaciones meteorológicas de puerto.

~147 estaciones en toda la costa (península, Baleares, Canarias, Ceuta y
Melilla): completan a AEMET en primera línea de costa y mar adentro, donde AEMET
apenas tiene estaciones. Cadencia de 10 min a 1 h según el equipo.

No hay API documentada: es la API JSON que usa el propio visor
(portus.puertos.es), sin clave:

    GET  estaciones/rt/WIND                 → catálogo de estaciones con viento
    POST lastData/station/{id}  ["WIND", …] → última medida de cada estación

Cada medida viene como entero + `factor` (valor real = valor / factor) y su
`unidad`. La fecha es UTC (comprobado contra la hora actual el 2026-10-06).

Solo España: se descarta la red `EXTERNOS`, boyas de otros organismos que el
visor también muestra (Marine Institute de Irlanda, UK Met Office, Météo-France,
Instituto Hidrográfico de Portugal). Las de la "Red exterior" sí se quedan
aunque estén a 10–50 km de la costa: son las boyas españolas de aguas profundas,
y el contorno terrestre las descartaría.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from ..red import FuenteNoDisponible, sesion
from . import lectura

BASE = "https://portus.puertos.es/portussvr/api"
EN_PARALELO = 8          # peticiones simultáneas: el visor público no es un CDN
REDES_EXTRANJERAS = {"EXTERNOS"}

_A_KMH = {"m/s": 3.6, "km/h": 1.0, "kn": 1.852, "nudos": 1.852}


# PORTUS escribe algunos nombres sin tildes ("Estacion Meteorologica de Bilbao").
_TILDES = {r"\bEstacion\b": "Estación", r"\bMeteorologica\b": "Meteorológica", r"\bMareografo\b": "Mareógrafo",
           r"\bOceanografica\b": "Oceanográfica", r"\bDarsena\b": "Dársena", r"\bMalaga\b": "Málaga",
           r"\bCadiz\b": "Cádiz", r"\bAlmeria\b": "Almería", r"\bCoruna\b": "Coruña", r"\bLeon\b": "León",
           r"\bGijon\b": "Gijón", r"\bMahon\b": "Mahón", r"\bMarin\b": "Marín", r"\bPrincipe\b": "Príncipe",
           r"\bVillagarcia\b": "Villagarcía", r"\bMeteorólogica\b": "Meteorológica"}


def _nombre(texto: str | None) -> str | None:
    if not texto:
        return texto
    for patron, bien in _TILDES.items():
        texto = re.sub(patron, bien, texto)
    return " ".join(texto.split())


def _valor(dato: dict) -> float | None:
    if dato.get("valor") in (None, "") or dato.get("averia"):
        return None
    return float(dato["valor"]) / float(dato.get("factor") or 1)


def _kmh(dato: dict | None) -> float | None:
    v = None if dato is None else _valor(dato)
    if v is None:
        return None
    unidad = (dato.get("unidad") or "").strip().lower()
    if unidad not in _A_KMH:
        raise FuenteNoDisponible(f"PORTUS: unidad de viento desconocida {dato.get('unidad')!r}")
    return v * _A_KMH[unidad]


def _lectura(estacion: dict, ultimo: dict) -> dict | None:
    datos = {d.get("paramEseoo"): d for d in ultimo.get("datos") or []}
    velocidad, racha = _kmh(datos.get("WindSpeed")), _kmh(datos.get("WindSpeedMax"))
    if velocidad is None and racha is None:
        return None
    fecha = datetime.strptime(ultimo["fecha"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    tipo = ("boya" if estacion.get("boya") else "mareógrafo" if estacion.get("mareografo")
            else "estación de puerto" if estacion.get("meteorologica") else "otra")
    temperatura = datos.get("AirTemp")
    return {**lectura(
        fuente="Puertos del Estado",
        id=str(estacion["id"]),
        nombre=_nombre(estacion.get("nombre")),
        lat=float(estacion["latitud"]),
        lon=float(estacion["longitud"]),
        fecha_utc=fecha.isoformat(),
        velocidad_kmh=velocidad,
        racha_kmh=racha,
        direccion_grados=None if "WindDir" not in datos else _valor(datos["WindDir"]),
        temperatura_c=None if temperatura is None else _valor(temperatura),
    ), "tipo_estacion": tipo, "red": (estacion.get("red") or {}).get("nombre")}


async def obtener_estaciones() -> list[dict]:
    async with sesion() as s:
        catalogo = (await s.get(f"{BASE}/estaciones/rt/WIND", params={"locale": "es"})).json()
    catalogo = [e for e in catalogo if e.get("disponible", True)
                and (e.get("red") or {}).get("nombre") not in REDES_EXTRANJERAS]

    limite = asyncio.Semaphore(EN_PARALELO)
    async with sesion(metodo="POST", cuerpo_json=["WIND", "AIR_TEMP"]) as s:
        async def ultima(estacion):
            async with limite:
                try:
                    r = await s.get(f"{BASE}/lastData/station/{estacion['id']}", params={"locale": "es"},
                                    reintentos=2)
                    return _lectura(estacion, r.json())
                except (FuenteNoDisponible, ValueError, KeyError):
                    return None     # una estación caída no invalida las demás
        lecturas = await asyncio.gather(*(ultima(e) for e in catalogo))
    lecturas = [l for l in lecturas if l]
    if catalogo and not lecturas:
        raise FuenteNoDisponible(f"PORTUS: ninguna de {len(catalogo)} estaciones devolvió viento")
    return lecturas
