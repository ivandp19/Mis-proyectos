"""
Incidencias oficiales de incendios forestales (servicios de emergencias de las
comunidades autónomas), en un único esquema.

Son las mismas fuentes que reúne incendiosespaña.es, consultadas en origen. Ninguna
tiene API documentada: son los servicios públicos que usan sus propios visores.

| Comunidad | Servicio | Acceso |
|---|---|---|
| Andalucía | INFOCA, "Visor incidentes" | ArcGIS FeatureServer público |
| Castilla-La Mancha | INFOCAM / FIDIAS, partes de incendio | ArcGIS FeatureServer público |
| Cataluña | Bombers de la Generalitat, actuaciones urgentes | ArcGIS FeatureServer público |
| Castilla y León | INFORCYL, emergencias en curso | JSON del visor (`/json/emergencias`) |

No está la Comunitat Valenciana: su visor (112cv) es un widget cerrado y no se ha
encontrado un servicio de datos público (comprobado el 2026-10-07).

Se guarda lo que no está extinguido, más lo detectado en los últimos `dias`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .red import FuenteNoDisponible, sesion

MADRID = ZoneInfo("Europe/Madrid")

INFOCA = ("https://utility.arcgis.com/usrsvcs/servers/d6d1c0079ddd4c7f8876d58e13fcf1ac/"
          "rest/services/INFOCA/AN_INCIDENTES_PRO/FeatureServer/2")
FIDIAS = "https://services-eu1.arcgis.com/LVA9E9zjh6QfM7Mo/arcgis/rest/services/PartesIncendio_APPWeb_Vista/FeatureServer/0"
BOMBERS = ("https://services7.arcgis.com/ZCqVt1fRXwwK6GF4/arcgis/rest/services/"
           "ACTUACIONS_URGENTS_online_PRO_AMB_FASE_VIEW/FeatureServer/0")
INFORCYL = "https://servicios.jcyl.es/incyl/json/emergencias"


def _ms(v) -> datetime | None:
    return None if v in (None, "") else datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.astimezone(timezone.utc).isoformat(timespec="minutes")


AVISO = "aviso sin fase"


def _estado(texto) -> str | None:
    """Normaliza el estado; Bombers lo publica en catalán (Actiu, Estabilitzat, Controlat, Extingit)."""
    t = (texto or "").strip().lower()
    if t == AVISO:
        return t
    for prefijos, normal in ((("extingu", "extingit"), "extinguido"), (("controla",), "controlado"),
                             (("estabiliz", "estabilitz"), "estabilizado"), (("activ", "actiu"), "activo")):
        if t.startswith(prefijos):
            return normal
    return t or None


def incidencia(*, fuente, comunidad, id, lat, lon, municipio, provincia, tipo, estado,
               inicio: datetime | None, fin: datetime | None = None, superficie_ha=None, medios=None,
               actualizado: datetime | None = None, nota: str | None = None) -> dict:
    return {"fuente": fuente, "comunidad": comunidad, "id": str(id), "lat": round(float(lat), 5),
            "lon": round(float(lon), 5), "municipio": municipio, "provincia": provincia, "tipo": tipo,
            "estado": _estado(estado), "inicio_utc": _iso(inicio), "fin_utc": _iso(fin),
            "actualizado_utc": _iso(actualizado),
            "superficie_ha": None if superficie_ha is None else round(float(superficie_ha), 2), "medios": medios,
            "nota": nota}


async def _arcgis(s, url: str, where: str = "1=1") -> list[dict]:
    """Todas las entidades de una capa ArcGIS, paginando de 2000 en 2000."""
    entidades, desplazamiento = [], 0
    while True:
        datos = (await s.get(f"{url}/query", params={
            "where": where, "outFields": "*", "outSR": 4326, "f": "json",
            "resultOffset": desplazamiento, "resultRecordCount": 2000})).json()
        if "error" in datos:
            raise FuenteNoDisponible(f"ArcGIS: {datos['error'].get('message')}")
        entidades += datos.get("features", [])
        if not datos.get("exceededTransferLimit"):
            return entidades
        desplazamiento += len(datos.get("features", []))


def _vigente(estado: str | None, inicio: datetime | None, limite: datetime) -> bool:
    return estado != "extinguido" or (inicio is not None and inicio >= limite)


async def _andalucia(s, limite):
    salida = []
    for f in await _arcgis(s, INFOCA):
        a, g = f["attributes"], f.get("geometry") or {}
        if "x" not in g:
            continue
        inicio = None
        if a.get("FECHA"):
            dia = _ms(a["FECHA"]).date()
            hh, mm, *_ = (a.get("HORA") or "00:00").split(":")
            inicio = datetime(dia.year, dia.month, dia.day, int(hh), int(mm), tzinfo=MADRID)
        estado = _estado(a.get("ESTADO"))
        if not _vigente(estado, inicio, limite):
            continue
        medios = {k: a.get(k) for k in ("MEDIOS_AEREOS", "VEHICULOS", "BRICAS", "TECNICOS",
                                        "GRUPOS_ESPECIALISTAS", "UMIF", "GRUPOS_APOYO") if a.get(k)}
        salida.append(incidencia(fuente="INFOCA", comunidad="Andalucía", id=a.get("OID_ENTERO"),
                                 lat=g["y"], lon=g["x"], municipio=a.get("TERMINO_MUNICIPAL"),
                                 provincia=a.get("PROVINCIA"), tipo="Incendio forestal", estado=estado,
                                 inicio=inicio, medios=medios or None))
    return salida


async def _castilla_la_mancha(s, limite):
    salida = []
    for f in await _arcgis(s, FIDIAS, "Siniestro = 'FORESTAL'"):
        a = f["attributes"]
        if a.get("FalsaAlarma") == "SI" or a.get("Latitud") is None:
            continue
        inicio, estado = _ms(a.get("Detección")), _estado(a.get("Estado"))
        if not _vigente(estado, inicio, limite):
            continue
        salida.append(incidencia(fuente="INFOCAM (FIDIAS)", comunidad="Castilla-La Mancha", id=a.get("CódigoIF"),
                                 lat=a["Latitud"], lon=a["Longitud"], municipio=a.get("Municipio"),
                                 provincia=a.get("Provincia"),
                                 tipo=f"{a.get('Clase_siniestro_forestal') or 'Siniestro'} forestal",
                                 estado=estado, inicio=inicio, fin=_ms(a.get("Extinción")),
                                 superficie_ha=a.get("SupTotal")))
    return salida


async def _cataluna(s, limite):
    salida = []
    for f in await _arcgis(s, BOMBERS):
        a, g = f["attributes"], f.get("geometry") or {}
        if "x" not in g:
            continue
        inicio = _ms(a.get("ACT_DAT_ACTUACIO"))
        # Sin fase asignada, Bombers solo ha abierto el aviso: no se puede afirmar que el
        # incendio esté activo (caso real: Alfarràs, 2026-10-07, aviso sin fase ni vehículos).
        nota = None
        if a.get("COM_FASE"):
            estado = _estado(a["COM_FASE"])
        elif a.get("ACT_DAT_FI"):
            estado = "extinguido"
        else:
            estado = AVISO
            nota = ("Bombers ha abierto el aviso pero aún no le ha asignado fase "
                    f"({a.get('ACT_NUM_VEH') or 0} vehículos registrados). No confirma que el incendio siga activo.")
        if not _vigente(estado, inicio, limite):
            continue
        salida.append(incidencia(fuente="Bombers de la Generalitat", comunidad="Cataluña", id=a.get("OBJECTID"),
                                 lat=g["y"], lon=g["x"], municipio=a.get("MUNICIPI_SIG") or a.get("MUNICIPI_DPX"),
                                 provincia=None, tipo=a.get("TAL_DESC_ALARMA2") or a.get("TAL_DESC_ALARMA1"),
                                 estado=estado, inicio=inicio, fin=_ms(a.get("ACT_DAT_FI")),
                                 actualizado=_ms(a.get("ACT_DAT_ACTUAL")), nota=nota,
                                 medios={"vehículos": a.get("ACT_NUM_VEH") or 0}))
    return salida


def _texto(v):
    """INFORCYL anida algunos campos ({"NOMBRE": …} o {"nombre": …}); otros llegan como texto."""
    if isinstance(v, dict):
        return v.get("NOMBRE") or v.get("nombre") or v.get("DESCRIPCION") or v.get("descripcion")
    return v


def _latlon_cyl(e: dict) -> tuple[float, float]:
    """
    INFORCYL llama `latitud`/`longitud` a lo que en realidad son coordenadas UTM
    ETRS89 en metros (`huso`, normalmente 30). Se convierten a grados.
    """
    y, x = float(e["latitud"]), float(e["longitud"])
    if abs(y) <= 90 and abs(x) <= 180:
        return y, x
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(f"EPSG:258{int(e.get('huso') or 30)}", "EPSG:4326", always_xy=True).transform(x, y)
    return lat, lon


def _medios_cyl(medios) -> dict | None:
    """Recuento por tipo de medio. El listado trae nombres de personas e IMEI: no se guardan."""
    cuenta: dict = {}
    for m in medios or []:
        tipo = _texto(m.get("TIPO")) or "otros"
        cuenta[tipo] = cuenta.get(tipo, 0) + 1
    return cuenta or None


def _fecha_cyl(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return _ms(v)
    for formato in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(v)[:19], formato).replace(tzinfo=MADRID)
        except ValueError:
            pass
    return None


async def _castilla_y_leon(s, limite):
    r = await s.get(INFORCYL)
    if not r.texto.strip():          # 204 sin contenido: no hay emergencias en curso
        return []
    salida = []
    for e in r.json().get("listaEmergencias") or []:
        if e.get("latitud") is None or e.get("longitud") is None or e.get("falsa_alarma"):
            continue
        inicio, estado = _fecha_cyl(e.get("fecha_inicio")), _estado(_texto(e.get("estado")))
        if not _vigente(estado, inicio, limite):
            continue
        lat, lon = _latlon_cyl(e)
        superficie = sum(v for k, v in e.items() if k.startswith("sup_") and isinstance(v, (int, float)))
        medios = _medios_cyl(e.get("medios"))
        if e.get("nivel_infocal"):
            medios = {**(medios or {}), "nivel INFOCAL": e["nivel_infocal"]}
        salida.append(incidencia(fuente="INFORCYL", comunidad="Castilla y León",
                                 id=f"{e.get('emergencia_cpm')}-{e.get('emergencia_num1')}-{e.get('emergencia_num2')}",
                                 lat=lat, lon=lon, municipio=_texto(e.get("municipio")),
                                 provincia=_texto(e.get("provincia")), tipo="Incendio forestal", estado=estado,
                                 inicio=inicio, fin=_fecha_cyl(e.get("fecha_extincion")),
                                 superficie_ha=superficie if superficie else None, medios=medios,
                                 nota=f"Causa: {e['causa']}" if e.get("causa") else None))
    return salida


async def obtener_incidencias(dias: int = 3) -> tuple[list[dict], dict]:
    """
    (incidencias, estado por comunidad). Cada comunidad va aislada: si una falla,
    las demás siguen y el fallo queda en el estado.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    fuentes = {"Andalucía (INFOCA)": _andalucia, "Castilla-La Mancha (FIDIAS)": _castilla_la_mancha,
               "Cataluña (Bombers)": _cataluna, "Castilla y León (INFORCYL)": _castilla_y_leon}
    async with sesion() as s:
        resultados = await asyncio.gather(*(f(s, limite) for f in fuentes.values()), return_exceptions=True)
    todas, estado = [], {}
    for nombre, r in zip(fuentes, resultados):
        if isinstance(r, Exception):
            estado[nombre] = f"error: {type(r).__name__}: {r}"
        else:
            estado[nombre] = len(r)
            todas += r
    if all(isinstance(r, Exception) for r in resultados):
        raise FuenteNoDisponible("ninguna comunidad respondió: " + "; ".join(map(str, estado.values())))
    todas.sort(key=lambda i: i["inicio_utc"] or "", reverse=True)
    return todas, estado
