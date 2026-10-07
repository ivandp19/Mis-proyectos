"""
Comprobación de claves con una petición mínima a cada servicio, para saber
ANTES de lanzar el pipeline si la clave pegada funciona.
"""
from __future__ import annotations

from . import config as cfg
from .red import FuenteNoDisponible, sesion
from .satelites import lsasaf
from .viento.aemet import BASE as AEMET_BASE


async def _aemet() -> str:
    clave = cfg.AEMET_API_KEY
    if not clave:
        return "omitida: sin clave"
    if clave.count(".") != 2:
        # La clave de AEMET es un JWT (tres bloques separados por puntos):
        # si no, casi seguro se pegó cortada o con algo de más.
        return "MAL: no parece una clave de AEMET (debe ser un JWT: xxx.yyy.zzz); ¿se pegó entera?"
    try:
        async with sesion() as s:
            sobre = (await s.get(f"{AEMET_BASE}/observacion/convencional/todas",
                                 params={"api_key": clave}, reintentos=1)).json()
    except FuenteNoDisponible as e:
        return f"MAL: AEMET rechazó la clave ({e})"
    return "OK" if sobre.get("estado") == 200 else f"MAL: {sobre.get('descripcion')}"


async def _firms() -> str:
    if not cfg.FIRMS_MAP_KEY:
        return "omitida: se usan los CSV públicos (funciona igual, sin clave)"
    try:
        async with sesion() as s:
            r = await s.get("https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/",
                            params={"MAP_KEY": cfg.FIRMS_MAP_KEY}, reintentos=1)
        datos = r.json()
    except (FuenteNoDisponible, ValueError):
        return "MAL: FIRMS no reconoce la MAP_KEY (o se agotó su cupo de 10 min)"
    return f"OK ({datos.get('current_transactions')}/{datos.get('transaction_limit')} peticiones usadas en la ventana)"


async def _lsasaf() -> str:
    if not (cfg.LSASAF_USER and cfg.LSASAF_PASSWORD):
        return "omitida: sin usuario/contraseña (SEVIRI no se descargará)"
    try:
        await lsasaf.obtener_focos(horas=0.5, max_ficheros=1)
    except FuenteNoDisponible as e:
        return f"MAL: {e}"
    return "OK"


async def verificar_claves() -> dict[str, str]:
    return {"AEMET": await _aemet(), "NASA FIRMS": await _firms(), "EUMETSAT LSA-SAF": await _lsasaf()}
