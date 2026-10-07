#!/usr/bin/env python3
"""
RETO INCENDIOS — crawling (crawl4ai) y datos

Lo usa `reto_incendios.ipynb`, y también funciona solo desde la terminal o importado
desde otra aplicación. Dos funciones, una por paso:

    crawlear()  → paso 1: descarga
    guardar()   → paso 2: escribe los ficheros (y `comprobar` los verifica)
    mapa()      → paso 2: genera el mapa del reto leyendo solo esos ficheros (sin `comun`)

Recoge todo lo que describe incendios en España y lo deja en ficheros:

| Capa | Fuente | Fichero |
|---|---|---|
| Focos de calor | NASA FIRMS (VIIRS, MODIS) y EUMETSAT LSA-SAF (SEVIRI) | `focos.geojson` |
| Áreas quemadas | Copernicus EFFIS | `areas_quemadas.geojson` |
| Incidencias 112 | INFOCA, INFOCAM/FIDIAS, Bombers, INFORCYL | `incidencias_112.geojson` |
| Riesgo previsto | AEMET (mapa oficial georreferenciado, 3 días) | `riesgo/riesgo_D{1,2,3}.png` + `riesgo/riesgo.json` |
| Cobertura del suelo | ESA WorldCover (local) | propiedad `cobertura` de cada foco e incidencia |

Además: `estado.json` (ok / omitida / error de cada fuente) y `manifiesto.json`
(qué fichero es cada capa y cuántos registros tiene).

Además genera el mapa del reto en la misma carpeta (`mapa_incendios.html`).

    python retos/reto_incendios.py
    python retos/reto_incendios.py --horas 48 --dias-incidencias 7
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from incendios import cobertura, incidencias as incid, riesgo  # noqa: E402
from incendios.pipeline import anotar, ejecutar, ejecutar_con_detalle, resumen  # noqa: E402
from incendios.satelites import effis, firms, lsasaf  # noqa: E402

RETO = "incendios"

# --------------------------------------------------------------------------- ficheros
# Utilidades propias de este reto (no hace falta `comun`): carpeta de salida, JSON, GeoJSON,
# manifiesto y comprobación de lo guardado.
SALIDA = Path(__file__).resolve().parent / "output"


def nueva_carpeta(reto: str = RETO) -> Path:
    """Crea `retos/output/<reto>/<fecha UTC>/` y la devuelve."""
    carpeta = SALIDA / reto / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def escribir_json(ruta: Path, datos, compacto: bool = False) -> None:
    ruta.write_text(json.dumps(datos, ensure_ascii=False, default=str,
                               **({"separators": (",", ":")} if compacto else {"indent": 2})), encoding="utf-8")


def leer_json(ruta: Path):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def coleccion(registros: list[dict], capa: str, geom=None) -> dict:
    """Registros -> FeatureCollection. `geom(registro)` da la geometría; si no, un punto con lat/lon."""
    features = []
    for r in registros:
        g = geom(r) if geom else None
        if not g and r.get("lat") is not None and r.get("lon") is not None:
            g = {"type": "Point", "coordinates": [r["lon"], r["lat"]]}
        props = {k: v for k, v in r.items() if k not in ("lat", "lon", "geometria")}
        features.append({"type": "Feature", "geometry": g, "properties": props})
    return {"type": "FeatureCollection", "name": capa, "features": features}


def manifiesto(carpeta: Path, reto: str, capas: dict, estado: dict, parametros: dict) -> Path:
    ruta = carpeta / "manifiesto.json"
    escribir_json(ruta, {"reto": reto, "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "parametros": parametros, "capas": capas, "estado": estado})
    return ruta


def comprobar(carpeta: Path) -> list[dict]:
    """Relee lo guardado y lo compara con el manifiesto: cada fichero debe existir y tener todos sus registros."""
    filas = []
    for capa, info in leer_json(carpeta / "manifiesto.json")["capas"].items():
        ruta, esperado, hallado = carpeta / info["fichero"], info["registros"], None
        try:
            datos = leer_json(ruta)
            hallado = len(datos["features"]) if info["tipo"] == "geojson" else len(datos["dias"])
            if info["tipo"] == "imagen":  # el riesgo son PNG: tienen que estar todos
                hallado = sum((carpeta / d["imagen"]).exists() and (carpeta / d["niveles"]).exists() for d in datos["dias"])
        except (OSError, ValueError, KeyError):
            pass
        filas.append({"capa": capa, "fichero": info["fichero"], "manifiesto": esperado, "en el fichero": hallado,
                      "ok": hallado == esperado})
    return filas



async def crawlear(horas_focos: int = 24, horas_seviri: float = 3, dias_effis: int = 7,
                   dias_incidencias: int = 3) -> dict:
    """Ejecuta todas las fuentes en paralelo. Una fuente caída no detiene las demás."""
    estado: dict = {}
    focos_firms, focos_seviri, areas, oficiales, prevision = await asyncio.gather(
        ejecutar(estado, "NASA FIRMS", firms.obtener_focos(horas_focos)),
        ejecutar(estado, "EUMETSAT LSA-SAF (SEVIRI)", lsasaf.obtener_focos(horas_seviri)),
        ejecutar(estado, "EFFIS (áreas quemadas)", effis.obtener_areas(dias_effis)),
        ejecutar_con_detalle(estado, "Incidencias 112 (oficiales)", incid.obtener_incidencias(dias_incidencias)),
        ejecutar(estado, "Riesgo de incendio (AEMET)", riesgo.obtener_prevision()),
    )
    # "0 focos" de SEVIRI solo significa "no hay fuego" si el satélite pudo ver España.
    await anotar(estado, "EUMETSAT LSA-SAF (SEVIRI)", "vigilancia", lsasaf.vigilancia_espana())
    focos = sorted(focos_firms + focos_seviri, key=lambda f: f["fecha_utc"], reverse=True)
    # Qué hay en el suelo de cada foco e incidencia (datos locales, sin red).
    await ejecutar(estado, cobertura.NOMBRE_FUENTE, cobertura.anotar_async(focos, oficiales))
    return {"focos": focos, "areas": areas, "incidencias": oficiales, "riesgo": prevision, "estado": estado}


def _png(data_uri: str, ruta: Path) -> None:
    ruta.write_bytes(base64.b64decode(data_uri.split(",", 1)[1]))


def guardar(resultado: dict, carpeta: Path, parametros: dict) -> Path:
    """Escribe los ficheros del contrato y devuelve la ruta del manifiesto."""
    capas = {}
    for capa, nombre, registros, geom, desc in (
        ("focos", "focos.geojson", resultado["focos"], None,
         "Focos de calor por satélite. confianza: alta/media/baja; frp_mw: potencia radiativa; "
         "cobertura: reparto del suelo en el píxel del foco (ESA WorldCover)."),
        ("areas_quemadas", "areas_quemadas.geojson", resultado["areas"], lambda a: a.get("geometria"),
         "Perímetros EFFIS publicados o revisados en la ventana. novedad: nueva/actualizada."),
        ("incidencias_112", "incidencias_112.geojson", resultado["incidencias"], None,
         "Incendios de los servicios autonómicos. estado: activo/estabilizado/controlado/aviso sin fase/extinguido."),
    ):
        escribir_json(carpeta / nombre, coleccion(registros, capa, geom), compacto=True)
        capas[capa] = {"fichero": nombre, "tipo": "geojson", "registros": len(registros), "descripcion": desc}

    if resultado["riesgo"]:
        (carpeta / "riesgo").mkdir(exist_ok=True)
        dias = []
        for r in resultado["riesgo"]:
            fichero, niveles = f"riesgo/riesgo_D{r['dia']}.png", f"riesgo/niveles_D{r['dia']}.png"
            _png(r["capa"], carpeta / fichero)
            _png(r["niveles"], carpeta / niveles)
            (s, o), (n, e) = r["limites"]
            dias.append({"dia": r["dia"], "fecha": r["fecha"], "validez": r["validez"], "imagen": fichero,
                         "niveles": niveles, "limites": r["limites"],
                         # Esquinas en el orden de MapLibre/Mapbox (`image` source): NO, NE, SE, SO.
                         "esquinas_lonlat": [[o, n], [e, n], [e, s], [o, s]],
                         "nivel_max": r["nivel_max"], "reparto_pct": r["reparto_pct"]})
        escribir_json(carpeta / "riesgo" / "riesgo.json", {
            "fuente": "AEMET, mapa de riesgo meteorológico de incendios forestales (© AEMET)",
            "proyeccion_imagen": "Web Mercator (EPSG:3857); se superpone sin reproyectar",
            "niveles": riesgo.NIVELES,
            "colores_rgb": [list(c) for c in riesgo.COLORES],
            "niveles_png": "gris: valor 0–5 = nivel, 255 = sin dato",
            "dias": dias})
        capas["riesgo"] = {"fichero": "riesgo/riesgo.json", "tipo": "imagen", "registros": len(dias),
                           "descripcion": "Riesgo previsto por AEMET para mañana y los dos días siguientes (6 niveles)."}

    escribir_json(carpeta / "estado.json", resultado["estado"])
    return manifiesto(carpeta, RETO, capas, resultado["estado"], parametros)


# --------------------------------------------------------------------------- mapa
# El mapa de este reto vive aquí: no depende de `comun`. Lee solo los ficheros que
# escribe `guardar()` y produce un HTML autocontenido (necesita internet para Leaflet y los tiles).
def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _propiedades(ruta: Path) -> list[dict]:
    """GeoJSON -> propiedades de cada registro, con lat/lon (o `_geom` si no es un punto)."""
    salida = []
    for f in _leer_json(ruta, {}).get("features", []):
        p, g = dict(f.get("properties") or {}), f.get("geometry")
        if g and g.get("type") == "Point":
            p["lon"], p["lat"] = g["coordinates"][:2]
        elif g:
            p["_geom"] = g
        salida.append(p)
    return salida


def _carpeta_reciente() -> Path:
    base = Path(__file__).resolve().parent / "output" / RETO
    carpetas = sorted(p for p in base.glob("*") if p.is_dir()) if base.exists() else []
    if not carpetas:
        raise FileNotFoundError(f"No hay datos de «{RETO}» en {base}: ejecuta antes el reto.")
    return carpetas[-1]


def _datos(c: Path) -> dict:
    riesgo = _leer_json(c / "riesgo" / "riesgo.json", {})
    for d in riesgo.get("dias", []):  # imagen incrustada: el HTML se puede mover o enviar
        img = c / d["imagen"]
        d["img"] = "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode() if img.exists() else None
    return {"focos": _propiedades(c / "focos.geojson"), "areas": _propiedades(c / "areas_quemadas.geojson"),
            "incidencias": _propiedades(c / "incidencias_112.geojson"), "riesgo": riesgo}


def mapa(carpeta: Path | None = None, abrir: bool = False) -> Path:
    """Mapa interactivo de este reto (`mapa_incendios.html`) en su carpeta; la más reciente si no se indica."""
    carpeta = Path(carpeta) if carpeta else _carpeta_reciente()
    datos = _datos(carpeta)
    datos.update(reto=RETO, carpeta=carpeta.name, estado=_leer_json(carpeta / "estado.json", {}),
                 manifiesto=_leer_json(carpeta / "manifiesto.json", {}))
    html = (PLANTILLA.replace("__CUERPO__", CUERPO).replace("__JS_COMUN__", JS_COMUN).replace("__JS__", JS)
            .replace("__DATOS__", json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")))
    destino = carpeta / "mapa_incendios.html"
    destino.write_text(html, encoding="utf-8")
    if abrir:
        webbrowser.open(destino.as_uri())
    return destino

PLANTILLA = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapa Incendios · España</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<style>
:root { color-scheme: dark; --noche:#13110f; --panel:#1c1916; --panel-alto:#26221e; --linea:#3a352f; --texto:#eee8de;
  --tenue:#a89f92; --mar:#0e171c; --limite:#6e655a; --brasa:#ec8a3c; --alto:#e5484d; --medio:#f08c2e; --bajo:#e6c229;
  --ok:#46a758; --frio:#4c9be8;
  --f-titular:"Barlow Condensed","Arial Narrow",system-ui,sans-serif; --f-texto:"Barlow",system-ui,-apple-system,"Segoe UI",sans-serif;
  --f-dato:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace; --radio:6px; }
html,body { height:100%; margin:0; }
body { background:var(--noche); color:var(--texto); font:15px/1.45 var(--f-texto); }
button,select,input { font:inherit; color:inherit; }
:focus-visible { outline:2px solid var(--brasa); outline-offset:2px; }
.app { height:100%; display:grid; grid-template-rows:auto 1fr auto; }
.barra { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:10px 20px; padding:10px 16px;
  border-bottom:1px solid var(--linea); background:var(--panel); }
.marca { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 14px; min-width:0; }
.marca h1 { margin:0; font:700 1.55rem/1 var(--f-titular); letter-spacing:.02em; text-transform:uppercase; }
.marca h1 span { color:var(--brasa); }
.sello { font:400 .78rem/1.3 var(--f-dato); color:var(--tenue); }
.mando { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.campo { display:flex; align-items:center; gap:8px; font:600 .72rem/1 var(--f-titular); letter-spacing:.08em; text-transform:uppercase; color:var(--tenue); }
select,.boton,input[type=search] { background:var(--panel-alto); border:1px solid var(--linea); border-radius:var(--radio); padding:7px 10px; font-size:.9rem; min-height:36px; box-sizing:border-box; }
select,.boton { cursor:pointer; }
.boton { display:inline-flex; align-items:center; gap:8px; font-weight:600; }
.boton:hover,select:hover { border-color:var(--limite); }
.boton[aria-expanded="true"] { border-color:var(--brasa); color:var(--brasa); }
.cuerpo { display:grid; grid-template-columns:minmax(0,1fr) 370px; min-height:0; }
.mapa-zona { position:relative; min-height:0; }
#mapa { position:absolute; inset:0; background:var(--mar); }
.leaflet-container { font-family:var(--f-texto); background:var(--mar); }
.desplegable { position:absolute; top:10px; right:10px; z-index:1003; width:min(340px,calc(100% - 20px)); max-height:calc(100% - 20px);
  overflow-y:auto; background:var(--panel-alto); border:1px solid var(--linea); border-radius:var(--radio); box-shadow:0 12px 32px rgba(0,0,0,.45); padding:6px 0; }
.desplegable[hidden], [hidden] { display:none !important; }
.capa { display:grid; grid-template-columns:18px 1fr auto; align-items:center; gap:4px 10px; padding:7px 14px; cursor:pointer; }
.capa:hover { background:rgba(255,255,255,.03); }
.capa input[type=checkbox] { accent-color:var(--brasa); width:16px; height:16px; margin:0; }
.capa .nom { font-weight:600; }
.capa .ayuda { grid-column:2 / -1; font-size:.76rem; color:var(--tenue); line-height:1.3; }
.capa .n { font:.76rem var(--f-dato); color:var(--tenue); }
.capa select { padding:2px 6px; min-height:26px; font-size:.78rem; }
.separa { height:1px; background:var(--linea); margin:4px 0; }
.sub { padding:4px 14px 10px 14px; display:grid; gap:8px; font-size:.88rem; }
.sub label.op { display:grid; grid-template-columns:auto 1fr auto; gap:9px; align-items:center; cursor:pointer; }
.sub label.op input { accent-color:var(--brasa); width:15px; height:15px; margin:0; }
.sub .fila-sel { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:center; }
.sub .fila-sel select { padding:3px 6px; min-height:28px; font-size:.82rem; }
.sub .tit { font:600 .72rem/1 var(--f-titular); letter-spacing:.1em; text-transform:uppercase; color:var(--tenue); }
.sub input[type=range] { accent-color:var(--brasa); width:100%; }
.leyenda { position:absolute; left:10px; bottom:26px; z-index:1002; background:rgba(28,25,22,.92); border:1px solid var(--linea);
  border-radius:var(--radio); padding:9px 12px; font-size:.78rem; display:grid; gap:6px; max-width:min(430px,calc(100% - 20px)); max-height:45%; overflow-y:auto; }
.ley-btn { justify-self:start; background:none; border:0; padding:0; cursor:pointer; font:600 .68rem/1 var(--f-titular); letter-spacing:.1em; text-transform:uppercase; color:var(--brasa); }
.ley-btn::after { content:" ▾"; } .ley-btn[aria-expanded="false"]::after { content:" ▸"; }
#leyenda-cuerpo { display:grid; gap:6px; }
.leyenda .tit { font:600 .68rem/1 var(--f-titular); letter-spacing:.1em; text-transform:uppercase; color:var(--tenue); }
.leyenda .fila { display:flex; flex-wrap:wrap; gap:4px 12px; align-items:center; }
.leyenda i { display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:5px; vertical-align:-1px; border:1px solid rgba(0,0,0,.6); }
.leyenda i.cuadro { border-radius:2px; } .leyenda i.barra-c { border-radius:2px; width:22px; height:8px; }
.parte { border-left:1px solid var(--linea); background:var(--panel); overflow-y:auto; min-height:0; padding:16px; display:grid; align-content:start; gap:20px; }
.parte h2 { margin:0; font:700 1.35rem/1.1 var(--f-titular); text-transform:uppercase; letter-spacing:.02em; }
.parte h3 { margin:0 0 8px; font:600 .78rem/1 var(--f-titular); letter-spacing:.1em; text-transform:uppercase; color:var(--tenue); display:flex; justify-content:space-between; gap:8px; }
.subt { margin:4px 0 0; color:var(--tenue); font-size:.84rem; }
.cifras { display:grid; grid-template-columns:1fr 1fr; gap:1px; background:var(--linea); border:1px solid var(--linea); border-radius:var(--radio); overflow:hidden; }
.cifra { background:var(--panel); padding:10px 12px; min-width:0; }
.cifra .v { font:600 1.6rem/1.05 var(--f-titular); font-variant-numeric:tabular-nums; }
.cifra .v small { font-size:.9rem; font-weight:500; color:var(--tenue); margin-left:3px; }
.cifra .e { font-size:.76rem; color:var(--tenue); margin-top:3px; overflow-wrap:anywhere; }
.cifra.alerta .v { color:var(--alto); }
.reparto { display:flex; height:10px; border-radius:3px; overflow:hidden; background:var(--linea); margin:6px 0 4px; }
.reparto span { display:block; height:100%; }
.nota { font-size:.76rem; color:var(--tenue); margin:4px 0 0; }
.lista { list-style:none; margin:0; padding:0; display:grid; gap:1px; }
.lista button { width:100%; text-align:left; background:transparent; border:0; border-radius:4px; padding:7px 8px; display:grid; grid-template-columns:auto 1fr auto; gap:10px; align-items:center; cursor:pointer; }
.lista button:hover { background:var(--panel-alto); }
.lista .punto { width:10px; height:10px; border-radius:50%; }
.lista .txt { min-width:0; }
.lista .l1 { display:block; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.lista .l2 { display:block; font:.74rem/1.3 var(--f-dato); color:var(--tenue); }
.lista .dato { font:500 .85rem var(--f-dato); font-variant-numeric:tabular-nums; white-space:nowrap; }
.vacio { color:var(--tenue); font-size:.84rem; margin:0; padding:4px 8px; }
.fuentes { list-style:none; margin:0; padding:0; display:grid; gap:6px; font-size:.84rem; }
.fuentes li { display:grid; grid-template-columns:auto 1fr auto; gap:8px; align-items:baseline; }
.chip { font:600 .66rem/1 var(--f-titular); letter-spacing:.08em; text-transform:uppercase; padding:3px 6px; border-radius:3px; border:1px solid currentColor; }
.chip.ok { color:var(--ok); } .chip.omitida { color:var(--tenue); } .chip.error { color:var(--alto); }
.fuentes .n { font:.76rem var(--f-dato); color:var(--tenue); }
.pie { border-top:1px solid var(--linea); padding:8px 16px; font-size:.74rem; color:var(--tenue); display:flex; flex-wrap:wrap; gap:4px 16px; justify-content:space-between; background:var(--panel); }
.marca-112,.flecha-v,.marca-sev { background:none; border:0; }
.marca-112 span { display:grid; place-items:center; width:100%; height:100%; border-radius:3px; border:2px solid; background:#1b1714; font:700 8px/1 var(--f-dato); }
.marca-112.activo span { animation:latido 1.6s ease-in-out infinite; }
@keyframes latido { 50% { box-shadow:0 0 0 5px rgba(229,72,77,.35); } }
.flecha-v svg { display:block; overflow:visible; transition:transform .2s; }
.flecha-v:hover svg { filter:drop-shadow(0 0 4px #fff); }
.leaflet-popup-content-wrapper,.leaflet-popup-tip { background:var(--panel-alto); color:var(--texto); box-shadow:0 10px 28px rgba(0,0,0,.5); border:1px solid var(--linea); }
.leaflet-popup-content { margin:12px 14px; font-size:.86rem; line-height:1.4; min-width:230px; }
.leaflet-container a.leaflet-popup-close-button { color:var(--tenue); }
.pop h4 { margin:0 0 2px; font:700 1.05rem/1.15 var(--f-titular); text-transform:uppercase; letter-spacing:.02em; }
.pop .de { color:var(--tenue); font-size:.78rem; margin-bottom:8px; }
.pop dl { margin:0; display:grid; grid-template-columns:auto 1fr; gap:3px 12px; }
.pop dt { color:var(--tenue); font-size:.78rem; } .pop dd { margin:0; font:.8rem var(--f-dato); font-variant-numeric:tabular-nums; }
.pop .alerta { color:var(--alto); font-weight:600; }
.leaflet-control-zoom a { background:var(--panel-alto); color:var(--texto); border-color:var(--linea); }
.leaflet-control-zoom a:hover { background:var(--panel); color:var(--brasa); }
.leaflet-control-attribution { background:rgba(19,17,15,.8) !important; color:var(--tenue); font-size:10px; }
.leaflet-control-attribution a { color:var(--tenue); }
@media (max-width:900px) { .app { height:auto; min-height:100%; } .cuerpo { grid-template-columns:minmax(0,1fr); }
  .mapa-zona { height:64vh; min-height:380px; } .parte { border-left:0; border-top:1px solid var(--linea); overflow:visible; } }
@media (prefers-reduced-motion:reduce) { .marca-112.activo span { animation:none; } .flecha-v svg { transition:none; } }
</style></head>
<body><div class="app">
  <header class="barra">
    <div class="marca"><h1>Incendios <span>·</span> España</h1><span class="sello" id="sello">—</span></div>
    <div class="mando">
      <label class="campo" for="sel-base">Mapa
        <select id="sel-base"><option value="oscuro">Oscuro</option><option value="claro">Claro</option><option value="calles">Calles</option><option value="satelite">Satélite</option></select></label>
      <button type="button" class="boton" id="btn-capas" aria-expanded="false" aria-controls="menu-capas">Capas y filtros <span aria-hidden="true">▼</span></button>
    </div>
  </header>
  <main class="cuerpo">
    <div class="mapa-zona">
      <div id="mapa" role="region" aria-label="Mapa interactivo de Focos, áreas quemadas, incidencias 112 y riesgo"></div>
      __CUERPO__
      <div class="leyenda"><button type="button" class="ley-btn" id="btn-leyenda" aria-expanded="true" aria-controls="leyenda-cuerpo">Leyenda</button>
        <div id="leyenda-cuerpo" aria-live="polite"></div></div>
    </div>
  </main>
  <footer class="pie"><span>Herramienta de investigación. No sustituye a los avisos oficiales: ante un incendio, llama al 112.</span>
    <span id="creditos"></span></footer>
</div>
<script id="datos" type="application/json">__DATOS__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<script>
__JS_COMUN__
__JS__
</script></body></html>
"""

JS_COMUN = r"""
const D = JSON.parse(document.getElementById('datos').textContent);
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v, d = 0) => (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString('es-ES', {maximumFractionDigits: d, minimumFractionDigits: d});
const fmtFecha = s => { if (!s) return '—'; const t = new Date(s); return isNaN(t) ? s :
  t.toLocaleString('es-ES', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', timeZone:'UTC'}) + ' UTC'; };
// Momento de la descarga: sale del nombre de la carpeta (20261007T135618Z); sirve de "ahora" para las ventanas de tiempo.
const REF = (() => { const m = /^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z$/.exec(D.carpeta || '');
  return m ? new Date(Date.UTC(+m[1], m[2]-1, +m[3], +m[4], +m[5], +m[6])) : new Date(); })();
$('#sello').textContent = 'Datos de ' + fmtFecha(REF.toISOString());

const BASES = {   // sin API key
  oscuro:   ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', 'Tiles © Esri', 16],
  claro:    ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', 'Tiles © Esri', 16],
  calles:   ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap', 19],
  satelite: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Imagery © Esri', 18],
};
const map = L.map('mapa', {preferCanvas: true, minZoom: 4, zoomSnap: .5}).setView([39.9, -3.7], 6);
let base = null;
function ponerBase(k) { if (base) map.removeLayer(base);
  base = L.tileLayer(BASES[k][0], {attribution: BASES[k][1], maxZoom: BASES[k][2]}).addTo(map); base.bringToBack(); }
$('#sel-base').onchange = e => ponerBase(e.target.value);
ponerBase('oscuro');

// Relieve: sombreado de laderas (Esri World Hillshade, sin clave) mezclado en modo "hard-light" sobre el mapa base
map.createPane('relieve'); map.getPane('relieve').style.zIndex = 250; map.getPane('relieve').style.mixBlendMode = 'hard-light';
map.getPane('relieve').style.pointerEvents = 'none';
const capaRelieve = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}',
  {pane: 'relieve', attribution: 'Relieve © Esri', maxZoom: 16, maxNativeZoom: 16, opacity: .7});
document.getElementById('menu-capas').insertAdjacentHTML('afterbegin', `
  <label class="capa"><input type="checkbox" id="c-relieve" checked><span class="nom">Relieve</span><span></span>
    <span class="ayuda">Sombreado de montañas y valles. En satélite no hace falta.</span></label>
  <div class="capa" style="cursor:default"><span></span><label class="nom" for="r-relieve">Intensidad del relieve</label><span class="n" id="v-relieve">70 %</span>
    <span class="ayuda"><input type="range" id="r-relieve" min="10" max="100" step="5" value="70" style="width:100%"></span></div>
  <div class="separa"></div>`);
const relieveOn = () => { document.getElementById('c-relieve').checked ? capaRelieve.addTo(map) : map.removeLayer(capaRelieve); };
document.getElementById('c-relieve').onchange = relieveOn;
document.getElementById('r-relieve').oninput = e => { capaRelieve.setOpacity(e.target.value / 100); document.getElementById('v-relieve').textContent = e.target.value + ' %'; };
relieveOn();

// Menú de capas y leyenda desplegables
const btn = $('#btn-capas'), menu = $('#menu-capas');
btn.onclick = () => { menu.hidden = !menu.hidden; btn.setAttribute('aria-expanded', String(!menu.hidden)); };
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !menu.hidden) btn.click(); });
$('#btn-leyenda').onclick = e => { const b = e.currentTarget, ab = b.getAttribute('aria-expanded') === 'true';
  b.setAttribute('aria-expanded', String(!ab)); $('#leyenda-cuerpo').hidden = ab; };
L.DomEvent.disableClickPropagation(menu); L.DomEvent.disableScrollPropagation(menu);

// Utilidades
const chk = id => $('#' + id).checked, val = id => $('#' + id).value;
function lista(sel, items, vacio) {   // items: {color, l1, l2, dato, ir}
  const ol = $(sel); ol.innerHTML = '';
  if (!items.length) { ol.innerHTML = `<li><p class="vacio">${esc(vacio)}</p></li>`; return; }
  for (const it of items) { const li = document.createElement('li'), b = document.createElement('button');
    b.type = 'button';
    b.innerHTML = `<span class="punto" style="background:${it.color}"></span><span class="txt"><span class="l1">${esc(it.l1)}</span><span class="l2">${esc(it.l2)}</span></span><span class="dato">${esc(it.dato)}</span>`;
    b.onclick = it.ir; li.append(b); ol.append(li); } }
function ir(latlng, capa, zoom) { map.flyTo(latlng, Math.max(map.getZoom(), zoom || 9), {duration: .6});
  if (capa) map.once('moveend', () => capa.openPopup()); }
function cifras(lista) { $('#cifras').innerHTML = lista.map(c =>
  `<div class="cifra ${c.alerta ? 'alerta' : ''}"><div class="v">${c.v}${c.u ? `<small>${c.u}</small>` : ''}</div><div class="e">${esc(c.e)}</div></div>`).join(''); }
function ley(bloques) { $('#leyenda-cuerpo').innerHTML = bloques.map(b => `<div><div class="tit">${esc(b.t)}</div><div class="fila">${b.f.join('')}</div></div>`).join(''); }
const dot = (c, t, cls = '') => `<span><i class="${cls}" style="background:${c}"></i>${esc(t)}</span>`;
function fuentes(estado) { const ul = $('#lista-fuentes'), ent = Object.entries(estado || {});
  ul.innerHTML = ent.length ? ent.map(([k, v]) => { v = v || {};
    const e = (v.estado || v.status || 'ok').toString().toLowerCase(), cls = ['ok','omitida','error'].includes(e) ? e : 'ok';
    const n = v.registros ?? v.n; return `<li><span class="chip ${cls}">${esc(e)}</span><span>${esc(k)}</span><span class="n">${n != null ? n : ''}</span></li>`; }).join('')
    : '<li><p class="vacio">Sin estado de fuentes.</p></li>'; }
const popup = (t, de, filas) => `<div class="pop"><h4>${esc(t)}</h4><div class="de">${esc(de)}</div><dl>` +
  filas.filter(f => f[1] != null && f[1] !== '').map(f => `<dt>${esc(f[0])}</dt><dd class="${f[2] || ''}">${esc(f[1])}</dd>`).join('') + `</dl></div>`;
function encuadrar(puntos) { if (puntos.length > 1) map.fitBounds(L.latLngBounds(puntos).pad(.15), {maxZoom: 8}); }
"""

CUERPO = r"""
      <div class="desplegable" id="menu-capas" hidden>
        <label class="capa"><input type="checkbox" id="c-riesgo"><span class="nom">Riesgo previsto</span>
          <select id="sel-dia" aria-label="Día de la previsión"></select>
          <span class="ayuda" id="ayuda-riesgo">Previsión oficial de AEMET del riesgo meteorológico de incendio (3 días).</span></label>
        <div class="capa" style="cursor:default"><span></span><label class="nom" for="r-op">Opacidad del riesgo</label><span class="n" id="v-op">65 %</span>
          <span class="ayuda"><input type="range" id="r-op" min="10" max="100" step="5" value="65" style="width:100%"></span></div>
        <label class="capa"><input type="checkbox" id="c-areas" checked><span class="nom">Áreas quemadas EFFIS</span><span class="n" id="n-areas"></span>
          <span class="ayuda">Perímetros publicados o revisados en la ventana.</span></label>
        <label class="capa"><input type="checkbox" id="c-112" checked><span class="nom">Incidencias 112</span><span class="n" id="n-112"></span>
          <span class="ayuda">Incendios de INFOCA, FIDIAS, Bombers e INFORCYL.</span></label>
        <label class="capa"><input type="checkbox" id="c-focos" checked><span class="nom">Focos de calor</span><span class="n" id="n-focos"></span>
          <span class="ayuda">Detecciones por satélite. El tamaño indica la potencia radiativa (FRP).</span></label>
        <div class="separa"></div>
        <div class="sub"><div class="tit">Focos de calor</div>
          <div id="sensores"></div>
          <div class="fila-sel"><label for="sel-conf">Confianza mínima</label>
            <select id="sel-conf"><option value="0">Todas</option><option value="1">Media o alta</option><option value="2">Solo alta</option></select></div>
          <div class="fila-sel"><label for="r-horas">Últimas <b id="v-horas">24</b> h</label><span></span></div>
          <input type="range" id="r-horas" min="1" max="24" step="1" value="24" aria-label="Ventana de tiempo de los focos">
          <label class="op"><input type="checkbox" id="c-solo-veg"><span>Solo vegetación natural (≥ 50 %)</span><span class="n" id="n-veg"></span></label>
        </div>
        <div class="separa"></div>
        <div class="sub"><div class="tit">Incidencias 112</div>
          <div class="fila-sel"><label for="sel-estado">Estado</label>
            <select id="sel-estado"><option value="">Todos</option><option value="vivos">Solo en curso (no extinguidos)</option><option value="extinguido">Solo extinguidos</option></select></div>
          <div class="fila-sel"><label for="sel-ccaa">Comunidad</label><select id="sel-ccaa"><option value="">Todas</option></select></div>
        </div>
      </div>
"""

JS = r"""
document.querySelector('.cuerpo').insertAdjacentHTML('beforeend', `
  <aside class="parte" aria-label="Parte de situación">
    <div><h2 id="r-titulo">Situación de incendios</h2><p class="subt" id="r-sub"></p></div>
    <div class="cifras" id="cifras"></div>
    <section id="sec-riesgo" hidden><h3><span>Riesgo previsto (AEMET)</span><span id="h-riesgo"></span></h3><div id="riesgo-zona"></div></section>
    <section><h3><span>Incidencias 112</span><span id="h-112"></span></h3><ol class="lista" id="lista-112"></ol></section>
    <section><h3><span>Focos de calor</span><span id="h-focos"></span></h3><ol class="lista" id="lista-focos"></ol></section>
    <section><h3><span>Áreas quemadas</span><span id="h-areas"></span></h3><ol class="lista" id="lista-areas"></ol></section>
    <section><h3><span>Estado de las fuentes</span></h3><ul class="fuentes" id="lista-fuentes"></ul></section>
  </aside>`);
$('#creditos').textContent = 'NASA FIRMS · EUMETSAT LSA SAF · Copernicus EFFIS · AEMET · INFOCA · INFOCAM · Bombers · INFORCYL · cobertura © ESA WorldCover';

const CONF = {alta: 2, media: 1, baja: 0}, COL_CONF = {alta: '#e5484d', media: '#f08c2e', baja: '#e6c229'};
const COL_RIESGO = (D.riesgo.colores_rgb || [[0,160,0],[140,200,40],[250,220,0],[250,140,0],[220,30,30],[120,0,0]]).map(c => `rgb(${c.join(',')})`);
const NIV = D.riesgo.niveles || ['Muy bajo','Bajo','Moderado','Alto','Muy alto','Extremo'];
const ahora = REF.getTime();
const horasDe = s => (ahora - new Date(s).getTime()) / 36e5;
const sensorDe = f => (f.sensor || (/seviri|meteosat/i.test(f.satelite || '') ? 'SEVIRI' : '?')).toString().toUpperCase();
const colorEstado = e => /activo/i.test(e || '') ? '#e5484d' : /estabiliz/i.test(e || '') ? '#f08c2e' : /control/i.test(e || '') ? '#e6c229'
  : /extingu/i.test(e || '') ? '#46a758' : '#a89f92';
const vivo = e => !/extingu/i.test(e || '');

// Grupos de capa
const gAreas = L.featureGroup().addTo(map), g112 = L.featureGroup().addTo(map), gFocos = L.featureGroup().addTo(map);
let capaRiesgo = null;

// Controles dinámicos
const sensores = [...new Set(D.focos.map(sensorDe))].sort();
$('#sensores').innerHTML = sensores.length ? sensores.map(s =>
  `<label class="op"><input type="checkbox" class="c-sensor" value="${esc(s)}" checked><span>${esc(s)}</span><span class="n">${D.focos.filter(f => sensorDe(f) === s).length}</span></label>`).join('')
  : '<p class="vacio">Sin focos en la ventana.</p>';
const maxH = Math.max(1, Math.ceil(Math.max(0, ...D.focos.map(f => horasDe(f.fecha_utc)).filter(isFinite))));
$('#r-horas').max = Math.max(maxH, 1); $('#r-horas').value = Math.max(maxH, 1); $('#v-horas').textContent = $('#r-horas').value;
for (const c of [...new Set(D.incidencias.map(i => i.comunidad).filter(Boolean))].sort()) $('#sel-ccaa').insertAdjacentHTML('beforeend', `<option>${esc(c)}</option>`);
$('#n-veg').textContent = D.focos.filter(f => f.cobertura && f.cobertura.combustible_pct >= 50).length;
if (!D.focos.some(f => f.cobertura)) { $('#c-solo-veg').disabled = true; $('#n-veg').textContent = 'sin dato'; }

// Riesgo (imagen georreferenciada, Web Mercator: Leaflet la coloca sin reproyectar)
const dias = (D.riesgo.dias || []).filter(d => d.img);
if (!dias.length) { $('#c-riesgo').disabled = true; $('#ayuda-riesgo').textContent = 'Sin previsión de riesgo en esta ejecución (falta la clave de AEMET o falló la fuente).'; }
$('#sel-dia').innerHTML = dias.map((d, i) => `<option value="${i}">${esc(d.fecha)}</option>`).join('');
function pintarRiesgo() {
  if (capaRiesgo) { map.removeLayer(capaRiesgo); capaRiesgo = null; }
  if (!dias.length || !chk('c-riesgo')) return;
  const d = dias[+val('sel-dia')], [[s, o], [n, e]] = d.limites;
  capaRiesgo = L.imageOverlay(d.img, [[s, o], [n, e]], {opacity: val('r-op') / 100, interactive: false}).addTo(map);
  capaRiesgo.bringToBack(); if (base) base.bringToBack();
}
$('#r-op').oninput = e => { $('#v-op').textContent = e.target.value + ' %'; capaRiesgo && capaRiesgo.setOpacity(e.target.value / 100); };

function panelRiesgo() {
  const sec = $('#sec-riesgo'); sec.hidden = !dias.length; if (!dias.length) return;
  const d = dias[+val('sel-dia')]; $('#h-riesgo').textContent = d.fecha;
  $('#riesgo-zona').innerHTML = `<div class="reparto" role="img" aria-label="Reparto del territorio por nivel de riesgo">` +
    NIV.map((n, i) => `<span style="width:${d.reparto_pct[n] || 0}%;background:${COL_RIESGO[i]}" title="${esc(n)}: ${d.reparto_pct[n] || 0} %"></span>`).join('') + `</div>` +
    `<div class="fila" style="display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.78rem">` +
    NIV.map((n, i) => `<span><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${COL_RIESGO[i]};margin-right:4px"></i>${esc(n)} ${num(d.reparto_pct[n], 1)} %</span>`).join('') + `</div>` +
    `<p class="nota">Nivel máximo previsto: <b>${esc(d.nivel_max)}</b>. ${esc(d.validez || '')}</p>`;
}

function render() {
  gAreas.clearLayers(); g112.clearLayers(); gFocos.clearLayers();
  const sens = new Set([...document.querySelectorAll('.c-sensor:checked')].map(i => i.value));
  const minConf = +val('sel-conf'), horas = +val('r-horas'), soloVeg = chk('c-solo-veg');
  const focos = D.focos.filter(f => f.lat != null && sens.has(sensorDe(f)) && (CONF[f.confianza] ?? 0) >= minConf &&
    horasDe(f.fecha_utc) <= horas + 1e-6 && (!soloVeg || (f.cobertura && f.cobertura.combustible_pct >= 50)));
  const inc = D.incidencias.filter(i => i.lat != null && (val('sel-estado') === '' || (val('sel-estado') === 'vivos' ? vivo(i.estado) : !vivo(i.estado))) &&
    (val('sel-ccaa') === '' || i.comunidad === val('sel-ccaa')));
  const areas = D.areas.filter(a => a._geom);

  const itemsA = areas.slice().sort((a, b) => (b.area_ha || 0) - (a.area_ha || 0)).map(a => {
    const col = a.novedad === 'nueva' ? '#e5484d' : '#f97316';
    const g = L.geoJSON(a._geom, {style: {color: col, weight: 2, fillColor: col, fillOpacity: .35}})
      .bindPopup(popup(a.municipio || 'Área quemada', `${a.provincia || ''} · EFFIS`, [
        ['Superficie', num(a.area_ha, 1) + ' ha'], ['Incendio', fmtFecha(a.fecha_incendio)], ['Novedad', a.novedad],
        ['Natura 2000', a.pct_natura2000 != null ? num(a.pct_natura2000, 0) + ' %' : null]]));
    g.on('mouseover', () => g.setStyle({weight: 3.5, fillOpacity: .55})); g.on('mouseout', () => g.setStyle({weight: 2, fillOpacity: .35}));
    if (chk('c-areas')) g.addTo(gAreas);
    return {color: col, l1: a.municipio || '—', l2: `${a.provincia || ''} · ${a.novedad || ''}`, dato: num(a.area_ha, 0) + ' ha',
      ir: () => { map.flyToBounds(g.getBounds().pad(.6), {maxZoom: 12, duration: .6}); map.once('moveend', () => g.openPopup(g.getBounds().getCenter())); }};
  });

  const itemsI = inc.slice().sort((a, b) => (b.inicio_utc || '').localeCompare(a.inicio_utc || '')).map(i => {
    const col = colorEstado(i.estado), est = i.estado || 'aviso sin fase';
    const m = L.marker([i.lat, i.lon], {icon: L.divIcon({className: 'marca-112' + (vivo(i.estado) ? ' activo' : ''), iconSize: [22, 22],
      html: `<span style="border-color:${col};color:${col}">112</span>`})})
      .bindPopup(popup(i.municipio || 'Incidencia', `${i.provincia || ''} · ${i.comunidad || ''}`, [
        ['Estado', est, vivo(i.estado) ? 'alerta' : ''], ['Inicio', fmtFecha(i.inicio_utc)], ['Superficie', i.superficie_ha != null ? num(i.superficie_ha, 1) + ' ha' : null],
        ['Suelo', i.cobertura && i.cobertura.dominante], ['Fuente', i.fuente]]));
    if (chk('c-112')) m.addTo(g112);
    return {color: col, l1: i.municipio || '—', l2: `${i.provincia || ''} · ${est}`, dato: fmtFecha(i.inicio_utc).replace(' UTC', ''), ir: () => ir(m.getLatLng(), m, 11)};
  });

  const itemsF = focos.slice().sort((a, b) => (b.frp_mw || 0) - (a.frp_mw || 0)).map(f => {
    const col = COL_CONF[f.confianza] || '#a89f92', r = 5 + Math.min(10, Math.sqrt(Math.max(f.frp_mw || 0, 0)) * 1.6);
    const m = L.circleMarker([f.lat, f.lon], {radius: r, color: '#1b1714', weight: 1, fillColor: col, fillOpacity: .85})
      .bindPopup(popup(`Foco · ${sensorDe(f)}`, `${f.satelite || ''} · confianza ${f.confianza || '—'}`, [
        ['Detectado', fmtFecha(f.fecha_utc)], ['Potencia (FRP)', f.frp_mw != null ? num(f.frp_mw, 1) + ' MW' : null],
        ['Suelo dominante', f.cobertura && f.cobertura.dominante], ['Vegetación natural', f.cobertura ? num(f.cobertura.combustible_pct, 0) + ' %' : null],
        ['Coordenadas', `${num(f.lat, 4)}, ${num(f.lon, 4)}`]]));
    m.on('mouseover', () => m.setStyle({weight: 3, color: '#fff'})); m.on('mouseout', () => m.setStyle({weight: 1, color: '#1b1714'}));
    if (chk('c-focos')) m.addTo(gFocos);
    return {color: col, l1: `${f.satelite || sensorDe(f)} · ${fmtFecha(f.fecha_utc).replace(' UTC', '')}`,
      l2: f.cobertura ? `${f.cobertura.dominante} · ${num(f.cobertura.combustible_pct, 0)} % veg.` : sensorDe(f),
      dato: f.frp_mw != null ? num(f.frp_mw, 1) + ' MW' : '—', ir: () => ir(m.getLatLng(), m, 10)};
  });

  // Paneles y cifras
  $('#n-focos').textContent = focos.length; $('#n-112').textContent = inc.length; $('#n-areas').textContent = areas.length;
  $('#h-focos').textContent = focos.length; $('#h-112').textContent = inc.length; $('#h-areas').textContent = areas.length;
  const frpMax = focos.reduce((m, f) => Math.max(m, f.frp_mw || 0), 0), ha = areas.reduce((s, a) => s + (a.area_ha || 0), 0);
  cifras([{v: inc.filter(i => vivo(i.estado)).length, e: 'incidencias 112 en curso', alerta: inc.some(i => vivo(i.estado))},
          {v: focos.length, e: `focos de calor · últimas ${horas} h`},
          {v: num(ha, 0), u: 'ha', e: `áreas quemadas (${areas.length})`},
          {v: num(frpMax, 1), u: 'MW', e: 'foco más potente'}]);
  $('#r-sub').textContent = `${D.focos.length} focos · ${D.areas.length} áreas · ${D.incidencias.length} incidencias en los datos`;
  lista('#lista-112', itemsI.slice(0, 40), 'Sin incidencias con estos filtros.');
  lista('#lista-focos', itemsF.slice(0, 40), 'Sin focos con estos filtros.');
  lista('#lista-areas', itemsA.slice(0, 40), 'Sin áreas quemadas.');
  panelRiesgo(); fuentes(D.estado);
  ley([{t: 'Focos (color = confianza, tamaño = potencia)', f: [dot(COL_CONF.alta, 'Alta'), dot(COL_CONF.media, 'Media'), dot(COL_CONF.baja, 'Baja')]},
       {t: 'Incidencias 112', f: [dot('#e5484d', 'Activo', 'cuadro'), dot('#f08c2e', 'Estabilizado', 'cuadro'), dot('#e6c229', 'Controlado', 'cuadro'),
                                  dot('#46a758', 'Extinguido', 'cuadro'), dot('#a89f92', 'Aviso sin fase', 'cuadro')]},
       {t: 'Áreas quemadas', f: [dot('#e5484d', 'Nueva', 'cuadro'), dot('#f97316', 'Actualizada', 'cuadro')]}]
      .concat(chk('c-riesgo') && dias.length ? [{t: 'Riesgo AEMET', f: NIV.map((n, i) => dot(COL_RIESGO[i], n, 'cuadro'))}] : []));
}

// Eventos: cualquier cambio de filtro repinta
$('#menu-capas').addEventListener('input', e => {
  if (e.target.id === 'r-op' || e.target.id === 'r-relieve' || e.target.id === 'c-relieve') return;
  if (e.target.id === 'r-horas') $('#v-horas').textContent = e.target.value;
  if (e.target.id === 'c-riesgo' || e.target.id === 'sel-dia') pintarRiesgo();
  render(); });
$('#menu-capas').addEventListener('change', e => { if (e.target.id === 'sel-dia') pintarRiesgo(); });
pintarRiesgo(); render();
encuadrar([...D.focos, ...D.incidencias].filter(p => p.lat != null).map(p => [p.lat, p.lon]).concat([[43.8, -9.3], [36, 3.3]]));
"""



def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horas", type=int, default=24, help="ventana de focos FIRMS (def. 24)")
    ap.add_argument("--horas-seviri", type=float, default=3, help="ventana de focos SEVIRI (def. 3)")
    ap.add_argument("--dias-effis", type=int, default=7, help="áreas quemadas publicadas o revisadas (def. 7)")
    ap.add_argument("--dias-incidencias", type=int, default=3, help="incidencias ya extinguidas a incluir (def. 3)")
    args = ap.parse_args()
    parametros = {"horas_focos": args.horas, "horas_seviri": args.horas_seviri,
                  "dias_effis": args.dias_effis, "dias_incidencias": args.dias_incidencias}
    resultado = asyncio.run(crawlear(**parametros))
    carpeta = nueva_carpeta(RETO)
    guardar(resultado, carpeta, parametros)
    print(f"\nReto INCENDIOS · datos guardados en {carpeta}\n\n{resumen(resultado['estado'])}")
    print(f"Mapa: {mapa(carpeta)}")


if __name__ == "__main__":
    main()
