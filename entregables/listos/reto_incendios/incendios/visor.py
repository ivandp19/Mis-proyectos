"""
Visor interactivo: una sola página HTML con los datos de una ejecución
incrustados, lista para abrir en el navegador o publicar como artifact.

Por qué los datos van dentro de la página y el mapa base son polígonos: el
artifact solo puede cargar scripts de unas pocas CDN (aquí Leaflet desde
cdnjs). No puede pedir teselas a ningún servidor de mapas ni datos en directo,
así que el fondo se dibuja con los límites de GISCO (`datos/`) y cada ejecución
del pipeline genera una página nueva con sus datos.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import cobertura as cob
from . import config as cfg
from .geo import paises

PLANTILLAS = Path(__file__).resolve().parent / "plantillas"
DATOS = Path(__file__).resolve().parent / "datos"


def _r(v, n=1):
    return None if v is None else round(float(v), n)


def _coords(c, n=4):
    if isinstance(c[0], (int, float)):
        return [round(c[0], n), round(c[1], n)]
    return [_coords(x, n) for x in c]


def _foco(f: dict) -> dict:
    v = f.get("viento_local") or {}
    return {"lat": round(f["lat"], 4), "lon": round(f["lon"], 4), "fuente": f["fuente"],
            "sensor": f["sensor"], "satelite": f["satelite"], "fecha": f["fecha_utc"],
            "conf": f["confianza"], "frp": _r(f.get("frp_mw")), "res": f.get("resolucion_m"),
            "dn": f.get("dia_noche"), "cobertura": f.get("cobertura"),
            "viento": {k: v.get(k) for k in ("velocidad_kmh", "racha_kmh", "direccion_cardinal",
                                              "hacia_grados", "temperatura_c", "humedad_pct", "regla_30")} if v else None}


def _area(a: dict) -> dict:
    return {"lat": round(a["lat"], 4), "lon": round(a["lon"], 4), "municipio": a.get("municipio"),
            "provincia": a.get("provincia"), "ha": a.get("area_ha"), "fecha": a.get("fecha_incendio"),
            "actualizada": a.get("ultima_actualizacion"), "novedad": a.get("novedad"),
            "natura": a.get("pct_natura2000"),
            "geom": None if not a.get("geometria") else {"type": a["geometria"]["type"],
                                                         "coordinates": _coords(a["geometria"]["coordinates"], 5)}}


def _viento(l: dict) -> dict:
    return {"lat": round(l["lat"], 4), "lon": round(l["lon"], 4), "nombre": " ".join((l.get("nombre") or "").split()),
            "fuente": l["fuente"], "tipo": l.get("tipo_estacion"), "fecha": l.get("fecha_utc"),
            "edad": l.get("antiguedad_min"), "vel": l.get("velocidad_kmh"), "racha": l.get("racha_kmh"),
            "dir": l.get("direccion_grados"), "card": l.get("direccion_cardinal"), "hacia": l.get("hacia_grados"),
            "t": l.get("temperatura_c"), "hr": l.get("humedad_pct"), "r30": l.get("regla_30")}


def _relieve() -> dict:
    """Modelo de elevación (PNG terrarium) como data URI, con sus límites."""
    meta = json.loads((DATOS / "relieve.json").read_text(encoding="utf-8"))
    for zona in meta["zonas"].values():
        zona["png"] = "data:image/png;base64," + base64.b64encode((DATOS / zona.pop("fichero")).read_bytes()).decode()
    return meta


def _incidencia(i: dict) -> dict:
    return {k: i.get(k) for k in ("fuente", "comunidad", "lat", "lon", "municipio", "provincia", "tipo",
                                  "estado", "inicio_utc", "fin_utc", "actualizado_utc", "superficie_ha", "medios", "nota",
                                  "cobertura")}


def _vecinos() -> list:
    """Contornos de los países vecinos, aligerados: solo son contexto en el mapa."""
    anillos = []
    for pais, poligonos in paises().items():
        if pais == "ESP":
            continue
        for _, poligono in poligonos:
            anillo = poligono[0]
            if len(anillo) < 8:
                continue
            paso = 3 if len(anillo) > 300 else 1
            anillos.append([[round(y, 3), round(x, 3)] for x, y in anillo[::paso]])
    return anillos


def generar(salida: Path, *, focos, areas, estaciones, costa, rejilla, estado,
            horas_focos: int, dias_effis: int, horas_seviri: float,
            incidencias=(), riesgo=(), dias_incidencias: int = 3,
            nombre: str = "visor.html", copia_publicar: bool = True) -> Path:
    """
    Escribe `salida/<nombre>` (por defecto `visor.html`), página completa para abrir
    con doble clic, y `output/visor_publicar.html`, la misma página sin la cabecera
    `<!doctype>…`, porque al publicar como artifact la plataforma pone la suya.
    Con `copia_publicar=False` no se escribe esa segunda copia (la usan los retos).
    """
    datos = {
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ventanas": {"horas_focos": horas_focos, "dias_effis": dias_effis, "horas_seviri": horas_seviri,
                     "dias_incidencias": dias_incidencias},
        "estado": estado,
        "focos": [_foco(f) for f in focos],
        "areas": [_area(a) for a in areas],
        "aemet": [_viento(l) for l in estaciones],
        "puertos": [_viento(l) for l in costa],
        "rejilla": [_viento(l) for l in rejilla],
        "incidencias": [_incidencia(i) for i in incidencias],
        "riesgo": list(riesgo),
        "relieve": _relieve(),
        "cobertura": cob.capa_visor(),        # None si no se ha generado (la opción del menú se desactiva)
        "regiones": json.loads((DATOS / "regiones_espana.geojson").read_text(encoding="utf-8")),
        "vecinos": _vecinos(),
    }
    # "</" dentro de un <script> cerraría la etiqueta antes de tiempo.
    incrustado = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    leaflet_css = re.sub(r"url\(images/[^)]*\)", "none",
                         (PLANTILLAS / "leaflet-1.9.4.css").read_text(encoding="utf-8"))
    html = (PLANTILLAS / "visor.html").read_text(encoding="utf-8")
    js = (PLANTILLAS / "visor.js").read_text(encoding="utf-8")
    html = (html.replace("/*__LEAFLET_CSS__*/", leaflet_css).replace("/*__VISOR_JS__*/", js)
            .replace("__DATOS__", incrustado))

    ruta = salida / nombre
    ruta.write_text(_CABECERA + html + "\n</body>\n</html>\n", encoding="utf-8")
    if copia_publicar:      # los retos no la tocan: es la versión completa del pipeline
        (cfg.DIR_SALIDA / "visor_publicar.html").write_text(html, encoding="utf-8")
    return ruta


_CABECERA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>*,*::before,*::after{box-sizing:border-box}body{margin:0}[hidden]{display:none!important}</style>
</head>
<body>
"""


# --- Comprobación y apertura ---------------------------------------------------------

def leer_datos(ruta: Path) -> dict:
    """Los datos incrustados en un visor ya generado (para comprobar qué lleva dentro)."""
    html = Path(ruta).read_text(encoding="utf-8")
    m = re.search(r'<script id="datos" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError(f"{ruta} no contiene datos del visor")
    return json.loads(m.group(1).replace("<\\/", "</"))


def comprobar(ruta: Path, *, focos, areas, estaciones, costa, rejilla, estado,
              incidencias=(), riesgo=()) -> list[dict]:
    """
    Compara, fuente por fuente, lo que hay en memoria (lo que acaba de sacar el
    pipeline) con lo que quedó incrustado en el visor. Devuelve una fila por
    comprobación con `ok` a True/False.
    """
    d = leer_datos(ruta)
    # Un visor generado con una versión anterior puede no tener alguna sección: cuenta como 0.
    for clave in ("focos", "areas", "incidencias", "riesgo", "aemet", "puertos", "rejilla"):
        d.setdefault(clave, [])
    d.setdefault("estado", {})
    filas = [
        ("Focos de satélite (FIRMS + SEVIRI)", len(focos), len(d["focos"])),
        ("Focos con viento en el punto", sum(1 for f in focos if f.get("viento_local")),
         sum(1 for f in d["focos"] if f.get("viento"))),
        ("Focos con cobertura del suelo", sum(1 for f in focos if f.get("cobertura")),
         sum(1 for f in d["focos"] if f.get("cobertura"))),
        ("Áreas quemadas EFFIS", len(areas), len(d["areas"])),
        ("Incidencias 112", len(incidencias), len(d["incidencias"])),
        ("Días de riesgo AEMET", len(riesgo), len(d["riesgo"])),
        ("Estaciones AEMET", len(estaciones), len(d["aemet"])),
        ("Estaciones Puertos del Estado", len(costa), len(d["puertos"])),
        ("Puntos Open-Meteo", len(rejilla), len(d["rejilla"])),
        ("Fuentes en el estado", len(estado), len(d["estado"])),
    ]
    salida = [{"comprobación": n, "pipeline": a, "visor": b, "ok": a == b} for n, a, b in filas]
    # Que los registros sean los mismos, no solo el mismo número: primer foco e incidencia.
    if focos and d["focos"]:
        salida.append({"comprobación": "Primer foco idéntico", "pipeline": focos[0]["fecha_utc"],
                       "visor": d["focos"][0]["fecha"], "ok": focos[0]["fecha_utc"] == d["focos"][0]["fecha"]})
    if incidencias and d["incidencias"]:
        salida.append({"comprobación": "Primera incidencia idéntica", "pipeline": incidencias[0]["municipio"],
                       "visor": d["incidencias"][0]["municipio"],
                       "ok": incidencias[0]["municipio"] == d["incidencias"][0]["municipio"]})
    sev = (estado.get("EUMETSAT LSA-SAF (SEVIRI)") or {}).get("vigilancia")
    if isinstance(sev, dict):
        sev_v = (d["estado"].get("EUMETSAT LSA-SAF (SEVIRI)") or {}).get("vigilancia") or {}
        salida.append({"comprobación": "Vigilancia SEVIRI (% de España)", "pipeline": sev["pct_vigilado"],
                       "visor": sev_v.get("pct_vigilado"), "ok": sev["pct_vigilado"] == sev_v.get("pct_vigilado")})
    salida.append({"comprobación": "Visor generado hace (min)", "pipeline": "—",
                   "visor": round((datetime.now(timezone.utc) - datetime.fromisoformat(d["generado_utc"])).total_seconds() / 60),
                   "ok": (datetime.now(timezone.utc) - datetime.fromisoformat(d["generado_utc"])).total_seconds() < 3600})
    return salida


def abrir(ruta: Path) -> bool:
    """Abre el visor en el navegador predeterminado del sistema."""
    import webbrowser

    return webbrowser.open(Path(ruta).resolve().as_uri())
