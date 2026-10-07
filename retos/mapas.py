#!/usr/bin/env python3
"""
MAPAS INTERACTIVOS DE LOS RETOS (Incendios y Vientos)

Genera un único HTML autocontenido por reto, con el mismo estilo "sala de operaciones" del
visor (barra de mando, mapa a la izquierda, parte a la derecha), pero adaptado a los datos
de cada reto. Lee SOLO los ficheros que escribe `guardar()`: no hace peticiones de datos.

    crear_mapa("incendios", carpeta)  ->  <carpeta>/mapa_incendios.html
    crear_mapa("vientos",   carpeta)  ->  <carpeta>/mapa_vientos.html

Misma firma que `comun.crear_mapa`: en `reto_incendios.py` y `reto_vientos.py` basta con
cambiar `from comun import ... crear_mapa ...` por `from mapas import crear_mapa`.

    python retos/mapas.py incendios [carpeta]
    python retos/mapas.py vientos   [carpeta]
"""
from __future__ import annotations

import base64
import json
import sys
import webbrowser
from pathlib import Path

SALIDA = Path(__file__).resolve().parent / "output"

TITULOS = {"incendios": ("Incendios", "Focos, áreas quemadas, incidencias 112 y riesgo"),
           "vientos": ("Vientos", "Estaciones AEMET, Puertos del Estado y Open-Meteo")}


# --------------------------------------------------------------------------- datos
def _json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _features(ruta: Path) -> list[dict]:
    """GeoJSON -> lista plana de propiedades, con lat/lon (y `_geom` si no es un punto)."""
    salida = []
    for f in _json(ruta, {}).get("features", []):
        p = dict(f.get("properties") or {})
        g = f.get("geometry")
        if g and g.get("type") == "Point":
            p["lon"], p["lat"] = g["coordinates"][:2]
        elif g:
            p["_geom"] = g
        salida.append(p)
    return salida


def _carpeta_reciente(reto: str) -> Path:
    base = SALIDA / reto
    carpetas = sorted(p for p in base.glob("*") if p.is_dir()) if base.exists() else []
    if not carpetas:
        raise FileNotFoundError(f"No hay datos de «{reto}» en {base}: ejecuta antes el reto.")
    return carpetas[-1]


def _datos_incendios(c: Path) -> dict:
    riesgo = _json(c / "riesgo" / "riesgo.json", {})
    for d in riesgo.get("dias", []):  # la imagen va incrustada: el HTML se puede mover o enviar
        img = c / d["imagen"]
        d["img"] = "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode() if img.exists() else None
    return {"focos": _features(c / "focos.geojson"), "areas": _features(c / "areas_quemadas.geojson"),
            "incidencias": _features(c / "incidencias_112.geojson"), "riesgo": riesgo}


def _datos_vientos(c: Path) -> dict:
    return {"lecturas": _features(c / "viento.geojson")}


def crear_mapa(reto: str, carpeta: Path | None = None, abrir: bool = False) -> Path:
    """Escribe `mapa_<reto>.html` en la carpeta del reto (la más reciente si no se indica)."""
    if reto not in TITULOS:
        raise ValueError(f"Reto desconocido: {reto!r} (usa 'incendios' o 'vientos')")
    carpeta = Path(carpeta) if carpeta else _carpeta_reciente(reto)
    datos = _datos_incendios(carpeta) if reto == "incendios" else _datos_vientos(carpeta)
    datos.update(reto=reto, carpeta=carpeta.name, estado=_json(carpeta / "estado.json", {}),
                 manifiesto=_json(carpeta / "manifiesto.json", {}))
    titulo, sub = TITULOS[reto]
    cuerpo, js = (CUERPO_INCENDIOS, JS_INCENDIOS) if reto == "incendios" else (CUERPO_VIENTOS, JS_VIENTOS)
    html = (PLANTILLA.replace("__TITULO__", titulo).replace("__SUB__", sub).replace("__CUERPO__", cuerpo)
            .replace("__JS_COMUN__", JS_COMUN).replace("__JS__", js)
            .replace("__DATOS__", json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")))
    destino = carpeta / f"mapa_{reto}.html"
    destino.write_text(html, encoding="utf-8")
    if abrir:
        webbrowser.open(destino.as_uri())
    return destino


# --------------------------------------------------------------------------- plantilla
PLANTILLA = r"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapa __TITULO__ · España</title>
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
    <div class="marca"><h1>__TITULO__ <span>·</span> España</h1><span class="sello" id="sello">—</span></div>
    <div class="mando">
      <label class="campo" for="sel-base">Mapa
        <select id="sel-base"><option value="oscuro">Oscuro</option><option value="claro">Claro</option><option value="satelite">Satélite</option></select></label>
      <button type="button" class="boton" id="btn-capas" aria-expanded="false" aria-controls="menu-capas">Capas y filtros <span aria-hidden="true">▼</span></button>
    </div>
  </header>
  <main class="cuerpo">
    <div class="mapa-zona">
      <div id="mapa" role="region" aria-label="Mapa interactivo de __SUB__"></div>
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

# --------------------------------------------------------------------------- JS común
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

const BASES = {
  oscuro:   ['https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', '© OpenStreetMap · © CARTO'],
  claro:    ['https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', '© OpenStreetMap · © CARTO'],
  satelite: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Imagery © Esri'],
};
const map = L.map('mapa', {preferCanvas: true, minZoom: 4, zoomSnap: .5}).setView([39.9, -3.7], 6);
let base = null;
function ponerBase(k) { if (base) map.removeLayer(base);
  base = L.tileLayer(BASES[k][0], {attribution: BASES[k][1], subdomains: 'abcd', maxZoom: 18}).addTo(map); base.bringToBack(); }
$('#sel-base').onchange = e => ponerBase(e.target.value);
ponerBase('oscuro');

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

# --------------------------------------------------------------------------- INCENDIOS
CUERPO_INCENDIOS = r"""
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

# El panel lateral del reto va fuera de .mapa-zona: se inyecta tras el mapa desde JS para no tocar la plantilla.
JS_INCENDIOS = r"""
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
  if (e.target.id === 'r-op') return;
  if (e.target.id === 'r-horas') $('#v-horas').textContent = e.target.value;
  if (e.target.id === 'c-riesgo' || e.target.id === 'sel-dia') pintarRiesgo();
  render(); });
$('#menu-capas').addEventListener('change', e => { if (e.target.id === 'sel-dia') pintarRiesgo(); });
pintarRiesgo(); render();
encuadrar([...D.focos, ...D.incidencias].filter(p => p.lat != null).map(p => [p.lat, p.lon]).concat([[43.8, -9.3], [36, 3.3]]));
"""

# --------------------------------------------------------------------------- VIENTOS
CUERPO_VIENTOS = r"""
      <div class="desplegable" id="menu-capas" hidden>
        <div class="sub"><div class="tit">Fuentes</div>
          <label class="op"><input type="checkbox" id="c-aemet" checked><span>Estaciones AEMET</span><span class="n" id="n-aemet"></span></label>
          <label class="op"><input type="checkbox" id="c-puertos" checked><span>Puertos del Estado (boyas y puertos)</span><span class="n" id="n-puertos"></span></label>
          <label class="op"><input type="checkbox" id="c-rejilla" checked><span>Open-Meteo, capitales (modelo)</span><span class="n" id="n-rejilla"></span></label>
        </div>
        <div class="separa"></div>
        <div class="sub"><div class="tit">Visualización</div>
          <div class="fila-sel"><label for="sel-metrica">Colorear por</label>
            <select id="sel-metrica"><option value="velocidad_kmh">Viento medio</option><option value="racha_kmh">Racha máxima</option><option value="temperatura_c">Temperatura</option><option value="humedad_pct">Humedad</option></select></div>
          <div class="fila-sel"><label for="sel-dir">Flecha indica</label>
            <select id="sel-dir"><option value="hacia_grados">Hacia dónde empuja</option><option value="direccion_grados">De dónde viene</option></select></div>
          <div class="fila-sel"><label for="r-esc">Tamaño de flecha</label><span class="n" id="v-esc">×1</span></div>
          <input type="range" id="r-esc" min=".6" max="2" step=".1" value="1" aria-label="Tamaño de las flechas">
        </div>
        <div class="separa"></div>
        <div class="sub"><div class="tit">Filtros</div>
          <div class="fila-sel"><label for="r-vmin">Viento mínimo: <b id="v-vmin">0</b> km/h</label><span></span></div>
          <input type="range" id="r-vmin" min="0" max="60" step="1" value="0" aria-label="Viento mínimo">
          <div class="fila-sel"><label for="sel-edad">Lecturas de hace como mucho</label>
            <select id="sel-edad"><option value="60">1 hora</option><option value="180">3 horas</option><option value="360">6 horas</option><option value="Infinity" selected>Todas</option></select></div>
          <label class="op"><input type="checkbox" id="c-r30"><span>Solo regla del 30 (&gt;30 °C, &lt;30 %, &gt;30 km/h)</span><span class="n" id="n-r30"></span></label>
        </div>
      </div>
"""

JS_VIENTOS = r"""
document.querySelector('.cuerpo').insertAdjacentHTML('beforeend', `
  <aside class="parte" aria-label="Parte de situación">
    <div><h2>Viento en España</h2><p class="subt" id="r-sub"></p></div>
    <div class="cifras" id="cifras"></div>
    <section><h3><span>Buscar estación</span></h3><input type="search" id="q" placeholder="Nombre de la estación…" style="width:100%" aria-label="Buscar estación"></section>
    <section><h3><span id="t-lista">Rachas más fuertes</span><span id="h-lista"></span></h3><ol class="lista" id="lista-viento"></ol></section>
    <section><h3><span>Antigüedad de las lecturas</span></h3><div id="edades"></div></section>
    <section><h3><span>Estado de las fuentes</span></h3><ul class="fuentes" id="lista-fuentes"></ul></section>
  </aside>`);
$('#creditos').textContent = 'AEMET OpenData · Puertos del Estado (iMar / PORTUS) · Open-Meteo';

const METRICAS = {
  velocidad_kmh: {n: 'Viento medio', u: 'km/h', cortes: [5, 15, 25, 35, 50], d: 0},
  racha_kmh:     {n: 'Racha máxima', u: 'km/h', cortes: [15, 30, 45, 60, 80], d: 0},
  temperatura_c: {n: 'Temperatura',  u: '°C',   cortes: [5, 12, 20, 28, 35], d: 1},
  humedad_pct:   {n: 'Humedad',      u: '%',    cortes: [20, 35, 50, 70, 85], d: 0},
};
const RAMPA = ['#4c9be8', '#3fb8a8', '#9acb4f', '#e6c229', '#f08c2e', '#e5484d'];
const colorDe = (m, v) => { if (v == null || isNaN(v)) return '#7d7468'; const c = METRICAS[m].cortes; let i = 0; while (i < c.length && v >= c[i]) i++; return RAMPA[i]; };
const FUENTES = {'AEMET': 'c-aemet', 'Puertos del Estado': 'c-puertos', 'Open-Meteo': 'c-rejilla'};
const L_ = D.lecturas.filter(l => l.lat != null);
for (const [f, id] of Object.entries(FUENTES)) { const n = L_.filter(l => l.fuente === f).length; $('#n-' + id.slice(2)).textContent = n; if (!n) $('#' + id).disabled = true; }
$('#n-r30').textContent = L_.filter(l => l.regla_30).length;

const grupo = L.featureGroup().addTo(map), registro = [];  // registro: {l, m}
const norm = s => (s || '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const GRUPO_BUSCA = {};

function flecha(l, metrica, dirCampo, esc_) {
  const col = colorDe(metrica, l[metrica]), v = l.velocidad_kmh || 0, tam = (12 + Math.min(18, v * .55)) * esc_;
  const rot = l[dirCampo] ?? l.hacia_grados, calma = rot == null || v < 1;
  const modelo = l.tipo_dato === 'modelo', r30 = !!l.regla_30;
  const forma = calma ? `<circle cx="12" cy="12" r="5" fill="${col}" stroke="#1b1714" stroke-width="1.5"/>`
    : `<path d="M12 1.5 L19 21 L12 16.5 L5 21 Z" fill="${modelo ? 'none' : col}" stroke="${r30 ? '#fff' : (modelo ? col : '#1b1714')}" stroke-width="${modelo || r30 ? 2 : 1.4}" stroke-linejoin="round"/>`;
  return L.divIcon({className: 'flecha-v', iconSize: [tam, tam], iconAnchor: [tam / 2, tam / 2],
    html: `<svg viewBox="0 0 24 24" width="${tam}" height="${tam}" style="transform:rotate(${calma ? 0 : rot}deg)">${forma}</svg>`});
}

function filtradas() {
  const act = new Set(Object.entries(FUENTES).filter(([, id]) => chk(id)).map(([f]) => f));
  const edad = +val('sel-edad'), vmin = +val('r-vmin'), r30 = chk('c-r30'), q = norm($('#q').value.trim());
  return L_.filter(l => act.has(l.fuente) && (l.antiguedad_min ?? 0) <= edad && (l.velocidad_kmh ?? 0) >= vmin && (!r30 || l.regla_30) && (!q || norm(l.nombre).includes(q)));
}

function render() {
  grupo.clearLayers(); registro.length = 0;
  const metrica = val('sel-metrica'), dirC = val('sel-dir'), esc_ = +val('r-esc'), ls = filtradas(), M = METRICAS[metrica];
  for (const l of ls) {
    const m = L.marker([l.lat, l.lon], {icon: flecha(l, metrica, dirC, esc_), keyboard: false, riseOnHover: true})
      .bindPopup(popup(l.nombre || 'Estación', `${l.fuente} · ${l.tipo_dato || ''} · hace ${num(l.antiguedad_min)} min`, [
        ['Viento medio', l.velocidad_kmh != null ? num(l.velocidad_kmh, 1) + ' km/h' : null], ['Racha', l.racha_kmh != null ? num(l.racha_kmh, 1) + ' km/h' : null],
        ['Viene de', l.direccion_grados != null ? `${l.direccion_cardinal || ''} (${num(l.direccion_grados)}°)` : null],
        ['Empuja hacia', l.hacia_grados != null ? num(l.hacia_grados) + '°' : null],
        ['Temperatura', l.temperatura_c != null ? num(l.temperatura_c, 1) + ' °C' : null], ['Humedad', l.humedad_pct != null ? num(l.humedad_pct) + ' %' : null],
        ['Regla del 30', l.regla_30 ? 'SE CUMPLE' : (l.regla_30 === false ? 'no' : null), l.regla_30 ? 'alerta' : '']]));
    m.addTo(grupo); registro.push({l, m});
  }
  // Panel
  const v = ls.map(l => l.velocidad_kmh).filter(x => x != null), rc = ls.map(l => l.racha_kmh).filter(x => x != null);
  const mejor = ls.reduce((b, l) => (l.racha_kmh ?? -1) > (b?.racha_kmh ?? -1) ? l : b, null), r30n = ls.filter(l => l.regla_30).length;
  cifras([{v: ls.length, e: `estaciones mostradas de ${L_.length}`},
          {v: v.length ? num(v.reduce((a, b) => a + b, 0) / v.length, 1) : '—', u: 'km/h', e: 'viento medio'},
          {v: rc.length ? num(Math.max(...rc), 0) : '—', u: 'km/h', e: mejor ? `racha máx. · ${mejor.nombre}` : 'racha máxima'},
          {v: r30n, e: 'en regla del 30', alerta: r30n > 0}]);
  $('#r-sub').textContent = Object.entries(FUENTES).map(([f]) => `${f}: ${L_.filter(l => l.fuente === f).length}`).join(' · ');
  const q = $('#q').value.trim(), top = registro.slice().sort((a, b) => (b.l.racha_kmh ?? -1) - (a.l.racha_kmh ?? -1)).slice(0, q ? 25 : 15);
  $('#t-lista').textContent = q ? 'Resultados' : 'Rachas más fuertes'; $('#h-lista').textContent = q ? ls.length : '';
  lista('#lista-viento', top.map(({l, m}) => ({color: colorDe(metrica, l[metrica]), l1: l.nombre || '—',
    l2: `${l.fuente} · ${l.direccion_cardinal || '—'} · ${num(l.velocidad_kmh, 0)} km/h`, dato: num(l.racha_kmh, 0) + ' km/h', ir: () => ir(m.getLatLng(), m, 10)})),
    'Ninguna estación con estos filtros.');
  // Antigüedad
  const tramos = [['≤ 30 min', 30], ['30–90 min', 90], ['1,5–3 h', 180], ['3–6 h', 360], ['> 6 h', Infinity]];
  const cnt = tramos.map(() => 0); for (const l of ls) { const a = l.antiguedad_min ?? 0; cnt[tramos.findIndex(t => a <= t[1])]++; }
  const mx = Math.max(1, ...cnt);
  $('#edades').innerHTML = tramos.map((t, i) => `<div style="display:grid;grid-template-columns:78px 1fr 40px;gap:8px;align-items:center;font-size:.8rem;margin:3px 0">
    <span>${t[0]}</span><span style="background:var(--linea);border-radius:3px;height:8px"><span style="display:block;height:100%;width:${cnt[i] / mx * 100}%;background:var(--brasa);border-radius:3px"></span></span>
    <span style="font-family:var(--f-dato);text-align:right">${cnt[i]}</span></div>`).join('');
  fuentes(D.estado);
  const rampa = RAMPA.map((c, i) => { const cs = M.cortes, t = i === 0 ? `< ${cs[0]}` : i === RAMPA.length - 1 ? `≥ ${cs[cs.length - 1]}` : `${cs[i - 1]}–${cs[i]}`;
    return dot(c, t, 'barra-c'); });
  ley([{t: `${M.n} (${M.u})`, f: rampa}, {t: 'Símbolos', f: ['<span>▲ flecha = dirección y fuerza</span>', '<span>△ hueca = modelo (Open-Meteo)</span>', '<span>◯ calma (&lt; 1 km/h)</span>', '<span style="color:#fff">▲ borde blanco = regla del 30</span>']}]);
}

$('#menu-capas').addEventListener('input', e => {
  if (e.target.id === 'r-esc') $('#v-esc').textContent = '×' + e.target.value;
  if (e.target.id === 'r-vmin') $('#v-vmin').textContent = e.target.value;
  render(); });
$('#q').addEventListener('input', () => { render(); const pts = registro.map(r => r.m.getLatLng()); if ($('#q').value.trim() && pts.length) encuadrar(pts); });
render();
encuadrar([[43.8, -9.3], [36, 3.3]]);
"""


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TITULOS:
        sys.exit(__doc__)
    print(crear_mapa(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else None))
