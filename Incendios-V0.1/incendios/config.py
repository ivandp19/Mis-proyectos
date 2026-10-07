"""
Configuración común del crawler de incendios.

Las credenciales se leen SIEMPRE del entorno (o de un `.env` en la raíz del
proyecto). Ninguna fuente que necesite clave rompe la ejecución si falta: se
marca como `omitida` en el estado de fuentes y el resto sigue.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_SALIDA = Path(os.environ.get("INCENDIOS_SALIDA", RAIZ / "output"))


def _cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """Lee un `.env` sencillo (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_env()

# --- Credenciales (todas opcionales) -----------------------------------------
# NASA FIRMS: sin clave se usan los CSV públicos de Europa (24h/48h/7d). Con
# MAP_KEY se usa la API de área, que permite pedir solo la zona de España y hasta 5 días.
# Alta gratuita: https://firms.modaps.eosdis.nasa.gov/api/map_key/
FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")

# EUMETSAT LSA-SAF (Meteosat SEVIRI, FRP-PIXEL cada 15 min). El servidor
# devuelve 401 sin usuario. Alta gratuita: https://mokey.lsasvcs.ipma.pt/auth/signup
LSASAF_USER = os.environ.get("LSASAF_USER", "")
LSASAF_PASSWORD = os.environ.get("LSASAF_PASSWORD", "")

# AEMET OpenData. Alta gratuita: https://opendata.aemet.es/centrodedescargas/altaUsuario
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "")

# --- Ámbito geográfico -------------------------------------------------------
# (oeste, sur, este, norte). Estas cajas son solo el PRE-filtro rápido y la
# zona que se pide a la API de FIRMS: incluyen Portugal, Andorra y franjas de
# Francia y Marruecos. El filtro "solo España" de verdad está en `geo.py`.
BBOX_PENINSULA_BALEARES = (-9.6, 35.1, 4.6, 44.0)   # sur 35.1: Melilla y Chafarinas
BBOX_CANARIAS = (-18.4, 27.5, -13.2, 29.5)
BBOXES_ESPANA = (BBOX_PENINSULA_BALEARES, BBOX_CANARIAS)


# --- Red -----------------------------------------------------------------------
USER_AGENT = "Incendios-V0.0/0.1 (crawl4ai; crawler de investigacion)"   # cabeceras HTTP: solo ASCII
TIMEOUT_S = 40
REINTENTOS = 3


# --- Claves desde el notebook ----------------------------------------------------
_CLAVES = {"aemet": "AEMET_API_KEY", "firms": "FIRMS_MAP_KEY",
           "lsasaf_usuario": "LSASAF_USER", "lsasaf_password": "LSASAF_PASSWORD"}


def fijar_claves(*, guardar_en_env: bool = False, **claves: str) -> None:
    """
    Fija las claves en caliente (las fuentes las leen al ejecutarse, no al
    importar). Las vacías se ignoran: se queda lo que hubiera en `.env`.

        fijar_claves(aemet="eyJ...", firms="", lsasaf_usuario="", lsasaf_password="")

    Con `guardar_en_env=True` se escriben además en `.env` (ignorado por git),
    para no tener que volver a pegarlas.
    """
    desconocidas = set(claves) - set(_CLAVES)
    if desconocidas:
        raise ValueError(f"claves desconocidas: {sorted(desconocidas)}; válidas: {sorted(_CLAVES)}")
    for nombre, valor in claves.items():
        valor = (valor or "").strip()
        if valor:
            globals()[_CLAVES[nombre]] = valor
            os.environ[_CLAVES[nombre]] = valor
    if guardar_en_env:
        _guardar_env()


def _guardar_env(ruta: Path = RAIZ / ".env") -> None:
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    pendientes = {var: globals()[var] for var in _CLAVES.values() if globals()[var]}
    salida = []
    for linea in lineas:
        var = linea.split("=", 1)[0].strip()
        salida.append(f"{var}={pendientes.pop(var)}" if var in pendientes else linea)
    salida += [f"{var}={valor}" for var, valor in pendientes.items()]
    ruta.write_text("\n".join(salida) + "\n", encoding="utf-8")


def estado_claves() -> dict[str, str]:
    """Qué claves hay, enmascaradas (nunca se imprime una clave entera)."""
    def mascara(v: str) -> str:
        return "— (vacía)" if not v else f"{v[:4]}…{v[-4:]} ({len(v)} caracteres)" if len(v) > 10 else "****"
    return {var: mascara(globals()[var]) for var in _CLAVES.values()}
