(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("datos").textContent);
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  const C = { alto: col("--alto"), medio: col("--medio"), bajo: col("--bajo"), ok: col("--ok"), frio: col("--frio"),
              sinDato: col("--sin-dato"), brasa: col("--brasa"), tierra: col("--tierra"), vecina: col("--tierra-vecina"),
              limite: col("--limite"), linea: col("--linea") };
  const sinMovimiento = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const RAD = Math.PI / 180;

  // --- Formato ---------------------------------------------------------------------
  const nf1 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 0 });
  const fh = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const fhora = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit" });
  const fdia = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", day: "numeric", month: "short" });
  const fsemana = new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", weekday: "long", day: "numeric", month: "short" });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, u = "", f = nf1) => (v == null ? "—" : f.format(v) + (u ? " " + u : ""));
  const cuando = (iso) => (iso ? fh.format(new Date(iso)) : "—");
  const edad = (min) => (min == null ? "" : min < 60 ? `hace ${min} min` : `hace ${nf1.format(min / 60)} h`);
  const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  // Cobertura del suelo (ESA WorldCover) en el píxel del foco: "bosque 60 % · matorral 30 %".
  const textoCobertura = (c) => (c ? Object.entries(c.fracciones_pct).slice(0, 3).map(([k, v]) => `${esc(k)} ${v} %`).join(" · ") : null);
  const CON_COMBUSTIBLE = 30;   // % mínimo de bosque + matorral + pasto para dibujar propagación
  const CARD = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"];
  const cardinal = (g) => (g == null ? "—" : CARD[Math.round(((g % 360) + 360) % 360 / 22.5) % 16]);
  const merc = (lat) => Math.log(Math.tan(Math.PI / 4 + lat * RAD / 2));
  const km = (a, b) => { const dLat = (b.lat - a.lat) * RAD, dLon = (b.lon - a.lon) * RAD;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * RAD) * Math.cos(b.lat * RAD) * Math.sin(dLon / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h)); };

  // --- Geometría: comunidad y provincia de cada punto ---------------------------------
  const regiones = D.regiones.features.map((f) => {
    const polis = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    let o = 180, s = 90, e = -180, n = -90;
    for (const p of polis) for (const [x, y] of p[0]) { o = Math.min(o, x); e = Math.max(e, x); s = Math.min(s, y); n = Math.max(n, y); }
    return { ...f.properties, polis, caja: [o, s, e, n], feature: f };
  });
  const comunidades = regiones.filter((r) => r.tipo === "comunidad").sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
  const provincias = regiones.filter((r) => r.tipo === "provincia");
  const enAnillo = (x, y, a) => { let d = false; for (let i = 0, j = a.length - 1; i < a.length; j = i++) {
    const [xi, yi] = a[i], [xj, yj] = a[j]; if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) d = !d; } return d; };
  const contiene = (r, lat, lon) => lon >= r.caja[0] && lon <= r.caja[2] && lat >= r.caja[1] && lat <= r.caja[3] &&
    r.polis.some((p) => enAnillo(lon, lat, p[0]) && !p.slice(1).some((h) => enAnillo(lon, lat, h)));
  const ubicar = (pt) => { pt.ccaa = (comunidades.find((r) => contiene(r, pt.lat, pt.lon)) || {}).id || null;
                           pt.prov = (provincias.find((r) => contiene(r, pt.lat, pt.lon)) || {}).nombre || null; return pt; };
  [D.focos, D.areas, D.aemet, D.puertos, D.rejilla, D.incidencias].forEach((l) => l.forEach(ubicar));
  const nombreCCAA = Object.fromEntries(comunidades.map((r) => [r.id, r.nombre]));
  const lugar = (p) => [p.prov || p.provincia, nombreCCAA[p.ccaa] || p.comunidad].filter(Boolean)
    .filter((v, i, a) => a.findIndex((w) => String(w).toLowerCase() === String(v).toLowerCase()) === i).map(esc).join(", ");

  // --- Escalas -----------------------------------------------------------------------
  const ORDEN_CONF = { baja: 0, media: 1, alta: 2 };
  const colorConf = (c) => ({ alta: C.alto, media: C.medio, baja: C.bajo }[c] || C.sinDato);
  const COLOR_ESTADO = { activo: C.alto, estabilizado: C.medio, controlado: C.bajo, "aviso sin fase": C.frio, extinguido: C.sinDato };
  const colorEstado = (e) => COLOR_ESTADO[e] || C.frio;
  const CORTES_VIENTO = [[15, C.ok, "< 15"], [30, C.bajo, "15–30"], [50, C.medio, "30–50"], [Infinity, C.alto, "≥ 50"]];
  const METRICAS = {
    viento: { campo: "vel", titulo: "Viento medio (km/h)", cortes: CORTES_VIENTO },
    racha: { campo: "racha", titulo: "Racha máxima (km/h)", cortes: CORTES_VIENTO },
    temperatura: { campo: "t", titulo: "Temperatura (°C)",
      cortes: [[15, C.frio, "< 15"], [25, C.ok, "15–25"], [30, C.bajo, "25–30"], [35, C.medio, "30–35"], [Infinity, C.alto, "≥ 35"]] },
    humedad: { campo: "hr", titulo: "Humedad relativa (%)",
      cortes: [[30, C.alto, "< 30"], [40, C.medio, "30–40"], [60, C.bajo, "40–60"], [Infinity, C.ok, "≥ 60"]] },
  };
  const colorMetrica = (m, v) => (v == null ? C.sinDato : m.cortes.find(([lim]) => v < lim)[1]);
  const NIVELES = ["Muy bajo", "Bajo", "Moderado", "Alto", "Muy alto", "Extremo"];
  const COLOR_NIVEL = ["rgb(70,130,200)", "rgb(80,190,230)", "rgb(90,200,70)", "rgb(240,220,40)", "rgb(240,130,20)", "rgb(220,30,30)"];
  const PENDIENTE = [[10, null], [20, [230, 200, 60, 115]], [30, [240, 140, 40, 150]], [Infinity, [225, 50, 50, 175]]];
  const TINTE = [[0, [52, 74, 52]], [200, [70, 92, 58]], [500, [108, 110, 66]], [900, [138, 116, 76]],
                 [1400, [150, 124, 96]], [2000, [172, 160, 144]], [3000, [228, 223, 214]]];
  const tinte = (h) => { for (let i = 1; i < TINTE.length; i++) if (h <= TINTE[i][0]) {
      const [h0, c0] = TINTE[i - 1], [h1, c1] = TINTE[i], t = (h - h0) / (h1 - h0);
      return [c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t]; }
    return TINTE[TINTE.length - 1][1]; };

  // --- Mapa base ---------------------------------------------------------------------
  const mapa = L.map("mapa", { preferCanvas: true, zoomSnap: 0.25, minZoom: 4, maxZoom: 13 });
  mapa.attributionControl.setPrefix(false);
  mapa.attributionControl.addAttribution("Límites © EuroGeographics (GISCO) · relieve AWS Terrain Tiles");
  const PENINSULA = L.latLngBounds([35.1, -9.8], [44.1, 4.6]);
  mapa.fitBounds(PENINSULA);
  const PANES = [["fondo", 200], ["relieve", 215], ["cobertura", 220], ["pendiente", 225], ["riesgo", 235], ["limites", 250], ["propagacion", 330],
                 ["areas", 380], ["viento", 450], ["incid", 600], ["focos", 620], ["acciones", 640]];
  for (const [nombre, z] of PANES) { const p = mapa.createPane(nombre); p.style.zIndex = z; if (["relieve", "cobertura", "pendiente", "riesgo"].includes(nombre)) p.style.pointerEvents = "none"; }
  const R = Object.fromEntries(["fondo", "limites", "propagacion", "areas", "focos"].map((p) => [p, L.canvas({ pane: p, tolerance: p === "focos" ? 4 : 0 })]));

  L.polygon(D.vecinos, { renderer: R.fondo, interactive: false, color: C.linea, weight: 0.8, fillColor: C.vecina, fillOpacity: 1 }).addTo(mapa);
  L.geoJSON(comunidades.map((r) => r.feature), { renderer: R.fondo, interactive: false, style: { stroke: false, fillColor: C.tierra, fillOpacity: 1 } }).addTo(mapa);
  const capaLimites = L.layerGroup([
    L.geoJSON(provincias.map((r) => r.feature), { renderer: R.limites, interactive: false, style: { color: "#d8cfc2", weight: 0.6, opacity: 0.45, fill: false, dashArray: "2 3" } }),
    L.geoJSON(comunidades.map((r) => r.feature), { renderer: R.limites, interactive: false, style: { color: "#efe6d8", weight: 1.3, opacity: 0.7, fill: false } }),
  ]).addTo(mapa);
  const resalte = L.geoJSON(null, { renderer: R.limites, interactive: false, style: { color: C.brasa, weight: 2.4, fill: false } }).addTo(mapa);

  // --- Relieve: elevación, sombreado, tintado y pendiente --------------------------------
  const REL = {};
  function cargarImagen(src) { return new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = src; }); }
  function pixeles(img) { const cv = document.createElement("canvas"); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    const cx = cv.getContext("2d", { willReadFrequently: true }); cx.drawImage(img, 0, 0); return cx.getImageData(0, 0, cv.width, cv.height).data; }

  async function cargarRelieve() {
    for (const [nombre, z] of Object.entries(D.relieve.zonas)) {
      const px = pixeles(await cargarImagen(z.png));
      const W = z.ancho, H = z.alto, n = W * H, alt = new Float32Array(n);
      for (let i = 0; i < n; i++) alt[i] = px[i * 4] * 256 + px[i * 4 + 1] - 32768;
      const [[la0, lo0], [la1, lo1]] = z.limites;
      const m0 = merc(la0), m1 = merc(la1), celEcuador = (lo1 - lo0) / 360 * 40075016 / W;
      const pend = new Float32Array(n), orient = new Float32Array(n);
      for (let y = 1; y < H - 1; y++) {
        const lat = Math.atan(Math.sinh(m1 - (y + 0.5) / H * (m1 - m0))) / RAD;
        const cel = celEcuador * Math.cos(lat * RAD);
        for (let x = 1; x < W - 1; x++) {
          const i = y * W + x;
          const a = alt[i - W - 1], b = alt[i - W], c = alt[i - W + 1], d = alt[i - 1], f = alt[i + 1], g = alt[i + W - 1], h = alt[i + W], k = alt[i + W + 1];
          const dzdx = ((c + 2 * f + k) - (a + 2 * d + g)) / (8 * cel), dzdy = ((g + 2 * h + k) - (a + 2 * b + c)) / (8 * cel);
          pend[i] = Math.atan(Math.hypot(dzdx, dzdy));
          orient[i] = Math.atan2(dzdy, -dzdx);
        }
      }
      REL[nombre] = { nombre, W, H, alt, pend, orient, la0, lo0, la1, lo1, m0, m1, celEcuador,
                      limites: z.limites, capa: null, capaPend: null, lienzo: null };
    }
  }
  const zonaDe = (lat, lon) => Object.values(REL).find((z) => lat >= z.la0 && lat <= z.la1 && lon >= z.lo0 && lon <= z.lo1);
  function muestraRelieve(lat, lon) {
    const z = zonaDe(lat, lon); if (!z) return null;
    const x = Math.floor((lon - z.lo0) / (z.lo1 - z.lo0) * z.W), y = Math.floor((z.m1 - merc(lat)) / (z.m1 - z.m0) * z.H);
    const i = y * z.W + x; return { alt: z.alt[i], pend: z.pend[i] / RAD };
  }

  const AZ = (360 - 315 + 90) * RAD, ZEN = 45 * RAD;   // sol al noroeste, 45° sobre el horizonte
  function lienzoRelieve(z, conTinte, conSombra, exag) {
    const cv = document.createElement("canvas"); cv.width = z.W; cv.height = z.H;
    const cx = cv.getContext("2d"), im = cx.createImageData(z.W, z.H), o = im.data;
    const cz = Math.cos(ZEN), sz = Math.sin(ZEN);
    for (let i = 0, n = z.W * z.H; i < n; i++) {
      const h = z.alt[i]; if (h <= 0) continue;
      let [r, g, b] = conTinte ? tinte(h) : [58, 53, 46];
      if (conSombra) { const s = Math.atan(exag * Math.tan(z.pend[i]));
        const hs = cz * Math.cos(s) + sz * Math.sin(s) * Math.cos(AZ - z.orient[i]);
        const f = Math.min(1.3, 0.28 + 1.0 * Math.max(0, hs)); r *= f; g *= f; b *= f; }
      const j = i * 4; o[j] = Math.min(255, r); o[j + 1] = Math.min(255, g); o[j + 2] = Math.min(255, b); o[j + 3] = 255;
    }
    cx.putImageData(im, 0, 0); return cv;
  }
  function lienzoPendiente(z) {
    const cv = document.createElement("canvas"); cv.width = z.W; cv.height = z.H;
    const cx = cv.getContext("2d"), im = cx.createImageData(z.W, z.H), o = im.data;
    for (let i = 0, n = z.W * z.H; i < n; i++) {
      if (z.alt[i] <= 0) continue;
      const g = z.pend[i] / RAD, c = PENDIENTE.find(([lim]) => g < lim)[1]; if (!c) continue;
      const j = i * 4; o[j] = c[0]; o[j + 1] = c[1]; o[j + 2] = c[2]; o[j + 3] = c[3];
    }
    cx.putImageData(im, 0, 0); return cv;
  }
  function pintarRelieve() {
    const tin = $("c-tintado").checked, som = $("c-sombreado").checked, pen = $("c-pendiente").checked, ex = +$("r-exag").value;
    for (const z of Object.values(REL)) {
      z.lienzo = (tin || som) ? lienzoRelieve(z, tin, som, ex) : null;
      if (z.lienzo) { const url = z.lienzo.toDataURL();
        if (z.capa) z.capa.setUrl(url); else z.capa = L.imageOverlay(url, z.limites, { pane: "relieve", interactive: false }); z.capa.addTo(mapa); }
      else z.capa?.remove();
      if (pen) { if (!z.capaPend) { z.lienzoPend = lienzoPendiente(z);
          z.capaPend = L.imageOverlay(z.lienzoPend.toDataURL(), z.limites, { pane: "pendiente", interactive: false }); }
        z.capaPend.addTo(mapa); }
      else z.capaPend?.remove();
    }
    if (vista) vista.actualizar();
  }

  // --- Riesgo (AEMET) ----------------------------------------------------------------
  const RIESGO = D.riesgo.map((r) => ({ ...r, overlay: L.imageOverlay(r.capa, r.limites, { pane: "riesgo", opacity: 0.62, interactive: false }) }));
  async function cargarRiesgo() {
    for (const r of RIESGO) {
      const img = await cargarImagen(r.niveles), px = pixeles(img);
      r.W = img.naturalWidth; r.H = img.naturalHeight; r.v = new Uint8Array(r.W * r.H);
      for (let i = 0; i < r.v.length; i++) r.v[i] = px[i * 4];
      r.img = await cargarImagen(r.capa);
      [[r.la0, r.lo0], [r.la1, r.lo1]] = r.limites; r.m0 = merc(r.la0); r.m1 = merc(r.la1);
    }
  }
  function nivelRiesgo(r, lat, lon) {
    if (!r || !r.v || lon < r.lo0 || lon > r.lo1 || lat < r.la0 || lat > r.la1) return null;
    const x = Math.floor((lon - r.lo0) / (r.lo1 - r.lo0) * r.W), y = Math.floor((r.m1 - merc(lat)) / (r.m1 - r.m0) * r.H);
    const v = r.v[y * r.W + x]; return v === 255 ? null : v;
  }
  const riesgoSel = () => RIESGO[+$("sel-dia").value] || null;
  for (const [i, r] of RIESGO.entries()) $("sel-dia").insertAdjacentHTML("beforeend", `<option value="${i}">${i === 0 ? "Mañana" : fdia.format(new Date(r.fecha + "T12:00:00Z"))}</option>`);
  if (!RIESGO.length) { $("c-riesgo").disabled = true; $("sel-dia").disabled = true;
    $("ayuda-riesgo").textContent = "Sin datos en esta ejecución: hace falta la clave de AEMET."; }
  function pintarRiesgo() { RIESGO.forEach((r) => r.overlay.remove()); const r = riesgoSel(); if ($("c-riesgo").checked && r) r.overlay.addTo(mapa); if (vista) vista.actualizar(); }

  // --- Cobertura del suelo (ESA WorldCover) ------------------------------------------------
  const COB = D.cobertura;
  const capasCobertura = COB ? Object.values(COB.zonas).map((z) => L.imageOverlay(z.png, z.limites, { pane: "cobertura", opacity: 0.7, interactive: false })) : [];
  const imgsCobertura = COB ? Object.values(COB.zonas).map((z) => { const i = new Image(); i.src = z.png; return { img: i, limites: z.limites }; }) : [];
  if (!COB) { $("c-cobertura").disabled = true; $("ayuda-cobertura").textContent = "Sin datos: genera la cobertura una vez con python herramientas/generar_cobertura.py."; }
  function pintarCobertura() { capasCobertura.forEach((c) => ($("c-cobertura").checked ? c.addTo(mapa) : c.remove())); if (vista) vista.actualizar(); }

  // --- Popups ----------------------------------------------------------------------------
  const filas = (pares) => "<dl>" + pares.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("") + "</dl>";
  function popFoco(f) {
    const v = f.viento, r = riesgoSel(), nr = nivelRiesgo(r, f.lat, f.lon), rel = muestraRelieve(f.lat, f.lon);
    return `<div class="pop"><h4>Foco ${esc(f.sensor)}</h4><div class="de">${esc(f.satelite)} · ${esc(f.fuente)}${lugar(f) ? " · " + lugar(f) : ""}</div>` +
      filas([["Detección", cuando(f.fecha) + " (peninsular)"], ["Confianza", esc(f.conf ?? "sin dato")], ["Potencia (FRP)", num(f.frp, "MW")],
             ["Píxel", f.res ? "≈ " + nf0.format(f.res) + " m" : null], ["Momento", f.dn ? esc(f.dn) : null],
             ["Viento en el foco", v ? `${num(v.velocidad_kmh, "km/h")} del ${esc(v.direccion_cardinal ?? "—")}` : null],
             ["Racha", v ? num(v.racha_kmh, "km/h") : null], ["Empuja hacia", v && v.hacia_grados != null ? `${cardinal(v.hacia_grados)} (${nf0.format(v.hacia_grados)}°)` : null],
             ["Temp. / humedad", v ? `${num(v.temperatura_c, "°C")} · ${num(v.humedad_pct, "%", nf0)}` : null],
             ["Regla del 30", v && v.regla_30 ? '<span class="alerta">Se cumple</span>' : v ? "No" : null],
             ["Suelo en el píxel", f.cobertura ? `${textoCobertura(f.cobertura)}` : null],
             ["Vegetación natural", f.cobertura ? `${f.cobertura.combustible_pct} % (bosque, matorral o pasto)` : null],
             ["Altitud / pendiente", rel ? `${nf0.format(rel.alt)} m · ${nf0.format(rel.pend)}°` : null],
             ["Riesgo AEMET", nr != null ? `${NIVELES[nr]} (${fdia.format(new Date(r.fecha + "T12:00:00Z"))})` : null]]) +
      `<div class="de" style="margin:8px 0 0">Viento: modelo Open-Meteo en la celda del foco.${f.cobertura ? ` Suelo: ESA WorldCover, ${nf0.format(2 * f.cobertura.radio_m)} m alrededor.` : ""}</div></div>`;
  }
  function popArea(a) {
    return `<div class="pop"><h4>${esc(a.municipio || "Área quemada")}</h4><div class="de">${esc(a.provincia || "")} · Copernicus EFFIS</div>` +
      filas([["Superficie", num(a.ha, "ha", nf0)], ["Fecha del incendio", a.fecha ? fdia.format(new Date(a.fecha)) : null],
             ["Actualizada por EFFIS", a.actualizada ? fdia.format(new Date(a.actualizada)) : null],
             ["Novedad", a.novedad === "nueva" ? "Nueva en la ventana" : "Perímetro revisado"],
             ["En Red Natura 2000", a.natura != null ? nf0.format(a.natura) + " %" : null]]) + "</div>";
  }
  function popEstacion(s) {
    return `<div class="pop"><h4>${esc(s.nombre || "Estación")}</h4><div class="de">${esc(s.fuente)}${s.tipo ? " · " + esc(s.tipo) : ""}${lugar(s) ? " · " + lugar(s) : ""}</div>` +
      filas([["Lectura", `${cuando(s.fecha)} · ${edad(s.edad)}`], ["Viento medio", num(s.vel, "km/h")], ["Racha máxima", num(s.racha, "km/h")],
             ["Viene del", s.dir != null ? `${esc(s.card)} (${nf0.format(s.dir)}°)` : "—"], ["Empuja hacia", s.hacia != null ? `${cardinal(s.hacia)} (${nf0.format(s.hacia)}°)` : "—"],
             ["Temperatura", num(s.t, "°C")], ["Humedad", num(s.hr, "%", nf0)],
             ["Regla del 30", s.r30 ? '<span class="alerta">Se cumple</span>' : s.r30 === false ? "No" : "Sin datos suficientes"]]) +
      (s.fuente === "Open-Meteo" ? '<div class="de" style="margin:8px 0 0">Dato de modelo, no medido.</div>' : "") + "</div>";
  }
  function popIncidencia(i) {
    const medios = i.medios ? Object.entries(i.medios).map(([k, v]) => `${esc(k.toLowerCase().replace(/_/g, " "))}: ${esc(v)}`).join(" · ") : null;
    return `<div class="pop"><h4>${esc(i.municipio || "Incidencia")}</h4><div class="de">${esc(i.fuente)} · ${lugar(i)}</div>` +
      filas([["Estado", `<span style="color:${colorEstado(i.estado)};font-weight:600">${esc(capital(i.estado) || "—")}</span>`],
             ["Tipo", esc(i.tipo)], ["Inicio", cuando(i.inicio_utc)], ["Última actualización", i.actualizado_utc ? cuando(i.actualizado_utc) : null],
             ["Fin", i.fin_utc ? cuando(i.fin_utc) : null],
             ["Superficie", i.superficie_ha != null ? num(i.superficie_ha, "ha") : null], ["Medios", medios],
             ["Suelo alrededor", i.cobertura ? textoCobertura(i.cobertura) : null]]) +
      (i.nota ? `<div class="de" style="margin:8px 0 0">${esc(i.nota)}</div>` : "") + "</div>";
  }

  // --- Capas de datos ------------------------------------------------------------------
  const capas = {};
  const marcadores = new Map();

  function dibujarFocos() {
    const minConf = +$("sel-conf").value;
    for (const k of ["firms", "seviri"]) { capas[k]?.remove(); capas[k] = L.layerGroup(); }
    for (const f of D.focos) {
      if ((ORDEN_CONF[f.conf] ?? 0) < minConf) continue;
      const sev = f.sensor === "SEVIRI";
      const m = L.circleMarker([f.lat, f.lon], { renderer: R.focos, radius: Math.min(4 + Math.sqrt(f.frp || 0) * 0.9, 17),
        color: sev ? "#ffffff" : "#1a1714", weight: sev ? 1.6 : 1, dashArray: sev ? "3 2" : null,
        fillColor: colorConf(f.conf), fillOpacity: 0.92 }).bindPopup(() => popFoco(f));
      m.addTo(capas[sev ? "seviri" : "firms"]); marcadores.set(f, m);
    }
    sincronizar();
  }
  function dibujarAreas() {
    capas.areas = L.layerGroup();
    for (const a of D.areas) {
      if (a.geom) L.geoJSON(a.geom, { renderer: R.areas, style: { color: "#f97316", weight: 1.2, fillColor: "#c2410c", fillOpacity: 0.4 } })
        .bindPopup(() => popArea(a)).addTo(capas.areas);
      const lado = Math.max(9, Math.min(18, 6 + Math.sqrt(a.ha || 0) * 1.6));
      const m = L.marker([a.lat, a.lon], { pane: "areas", keyboard: false, title: `${a.municipio || "Área quemada"}: ${nf0.format(a.ha || 0)} ha`,
        icon: L.divIcon({ className: "marca-area", html: "<span></span>", iconSize: [lado, lado] }) }).bindPopup(() => popArea(a));
      m.addTo(capas.areas); marcadores.set(a, m);
    }
  }
  function dibujarIncidencias() {
    capas["112"] = L.layerGroup();
    for (const i of D.incidencias) {
      const c = colorEstado(i.estado);
      const m = L.marker([i.lat, i.lon], { pane: "incid", title: `${i.municipio || "Incidencia"} · ${i.estado || ""}`,
        icon: L.divIcon({ className: "marca-112" + (i.estado === "activo" ? " activo" : ""), iconSize: [20, 20],
          html: `<span style="border-color:${c};color:${c}">112</span>` }) }).bindPopup(() => popIncidencia(i));
      m.addTo(capas["112"]); marcadores.set(i, m);
    }
  }
  function glifo(s, color, modelo) {
    const borde = modelo ? 'stroke="#eee8de" stroke-width="1" stroke-dasharray="2 1.5"' : 'stroke="#14110e" stroke-width="1.1"';
    const anillo = s.r30 ? '<circle cx="12" cy="12" r="11" fill="none" stroke="#e5484d" stroke-width="2"/>' : "";
    if (s.hacia == null || (s.vel == null && s.racha == null))
      return `<svg width="12" height="12" viewBox="0 0 24 24">${anillo}<circle cx="12" cy="12" r="6" fill="${color}" ${borde}/></svg>`;
    return `<svg width="22" height="22" viewBox="0 0 24 24">${anillo}<g transform="rotate(${s.hacia} 12 12)">` +
      `<path d="M12 2.5 L17.5 11 H13.6 V21.5 H10.4 V11 H6.5 Z" fill="${color}" ${borde} stroke-linejoin="round"/></g></svg>`;
  }
  // Estaciones: a escala nacional hay ~950 y se tapan entre sí. Se reparte el mapa en
  // celdas de ~30 px y en cada una se pinta la de racha más fuerte (las que cumplen la
  // regla del 30 tienen prioridad). Desde el zoom 9 se ven todas.
  const CELDA_PX = 30, ZOOM_TODAS = 9;
  const todasEst = { aemet: [], puertos: [], rejilla: [] };
  function dibujarEstaciones() {
    const m = METRICAS[$("sel-metrica").value], maxEdad = +$("sel-edad").value, soloR30 = $("c-r30").checked;
    for (const [k, lista, modelo] of [["aemet", D.aemet, false], ["puertos", D.puertos, false], ["rejilla", D.rejilla, true]]) {
      todasEst[k] = [];
      for (const s of lista) {
        if ((s.edad ?? 0) > maxEdad || (soloR30 && !s.r30)) continue;
        const tam = s.hacia == null ? 12 : 22;
        const mk = L.marker([s.lat, s.lon], { pane: "viento", keyboard: false, title: s.nombre || "",
          icon: L.divIcon({ className: "est", html: glifo(s, colorMetrica(m, s[m.campo]), modelo), iconSize: [tam, tam] }) }).bindPopup(() => popEstacion(s));
        todasEst[k].push([s, mk]); marcadores.set(s, mk);
      }
    }
    aclarar();
  }
  function aclarar() {
    const z = mapa.getZoom(), ocupadas = new Map();
    const prioridad = (s) => (s.r30 ? 1000 : 0) + (s.racha ?? s.vel ?? -1);
    for (const k of ["aemet", "puertos", "rejilla"]) {
      capas[k]?.remove(); capas[k] = L.layerGroup();
      for (const [s, mk] of todasEst[k]) {
        if (z >= ZOOM_TODAS) { mk.addTo(capas[k]); continue; }
        const p = mapa.project([s.lat, s.lon], z), clave = Math.floor(p.x / CELDA_PX) + ":" + Math.floor(p.y / CELDA_PX);
        const actual = ocupadas.get(clave);
        if (!actual || prioridad(s) > prioridad(actual[0])) ocupadas.set(clave, [s, mk, k]);
      }
    }
    if (z < ZOOM_TODAS) for (const [, mk, k] of ocupadas.values()) mk.addTo(capas[k]);
    sincronizar();
  }
  mapa.on("zoomend", aclarar);

  // --- Grupos de focos, propagación y acciones -------------------------------------------
  // Varios píxeles y pasadas de un mismo incendio se agrupan (≤ 1,5 km) para no repetir.
  function agrupar(focos) {
    const grupos = [];
    for (const f of [...focos].sort((a, b) => (b.frp || 0) - (a.frp || 0))) {
      const g = grupos.find((g) => km(g, f) <= 1.5);
      if (g) g.focos.push(f); else grupos.push({ lat: f.lat, lon: f.lon, focos: [f] });
    }
    for (const g of grupos) {
      const t = g.focos.map((f) => +new Date(f.fecha));
      g.frp = Math.max(...g.focos.map((f) => f.frp || 0));
      g.conf = g.focos.reduce((m, f) => ((ORDEN_CONF[f.conf] ?? -1) > (ORDEN_CONF[m] ?? -1) ? f.conf : m), null);
      g.pasadas = new Set(g.focos.map((f) => f.fecha)).size;
      g.horas = (Math.max(...t) - Math.min(...t)) / 3.6e6;
      g.ultima = new Date(Math.max(...t)).toISOString();
      g.viento = g.focos.map((f) => f.viento).filter(Boolean).sort((a, b) => (b.racha_kmh || 0) - (a.racha_kmh || 0))[0] || null;
      g.satelites = [...new Set(g.focos.map((f) => f.satelite))];
      g.cobertura = g.focos.find((f) => f.cobertura)?.cobertura || null;   // del foco más potente con dato
      ubicar(g);
    }
    return grupos;
  }
  const GRUPOS = agrupar(D.focos);

  // Propagación ilustrativa: avance de cabeza = 10 % del viento a 10 m (regla de Cruz y
  // Alexander, 2019) y forma elíptica de Anderson (1983) con viento a media llama ≈ 0,4 × viento a 10 m.
  function elipse(g, horas) {
    const v = g.viento; if (!v || v.velocidad_kmh == null || v.hacia_grados == null) return null;
    const U = v.velocidad_kmh, ros = 0.1 * U, cabeza = ros * horas; if (cabeza < 0.05) return null;
    const mph = U * 0.621371 * 0.4;
    const LB = Math.max(1.0001, Math.min(8, 0.936 * Math.exp(0.2566 * mph) + 0.461 * Math.exp(-0.1548 * mph) - 0.397));
    const raiz = Math.sqrt(LB * LB - 1), HB = (LB + raiz) / (LB - raiz);
    const cola = cabeza / HB, a = (cabeza + cola) / 2, b = a / LB, desplaz = cabeza - a, rumbo = v.hacia_grados * RAD;
    const pts = [];
    for (let k = 0; k <= 64; k++) {
      const t = (k / 64) * 2 * Math.PI, x = desplaz + a * Math.cos(t), y = b * Math.sin(t);
      const este = x * Math.sin(rumbo) + y * Math.cos(rumbo), norte = x * Math.cos(rumbo) - y * Math.sin(rumbo);
      pts.push([g.lat + norte / 111.32, g.lon + este / (111.32 * Math.cos(g.lat * RAD))]);
    }
    return { pts, cabeza, cola, ancho: 2 * b, ros, LB };
  }
  function dibujarPropagacion() {
    capas.propagacion?.remove(); capas.propagacion = L.layerGroup();
    const horas = +$("sel-horizonte").value;
    for (const g of GRUPOS) {
      g.elipse = null;
      if (g.cobertura && g.cobertura.combustible_pct < CON_COMBUSTIBLE) continue;   // cultivo, urbano, agua…: no es fuego forestal
      const e = elipse(g, horas); if (!e) continue;
      g.elipse = e;
      L.polygon(e.pts, { renderer: R.propagacion, color: C.brasa, weight: 1.4, dashArray: "5 4", fillColor: C.brasa, fillOpacity: 0.14 })
        .bindPopup(`<div class="pop"><h4>Propagación ilustrativa · ${horas} h</h4><div class="de">${lugar(g) || "Foco"} · no es una simulación</div>` +
          filas([["Viento en el foco", `${num(g.viento.velocidad_kmh, "km/h")} hacia el ${cardinal(g.viento.hacia_grados)}`],
                 ["Suelo en el foco", g.cobertura ? textoCobertura(g.cobertura) : "sin dato"],
                 ["Avance de cabeza", `${num(e.ros, "km/h")} → ${num(e.cabeza, "km")} en ${horas} h`], ["Retroceso (cola)", num(e.cola, "km", nf1)],
                 ["Anchura máxima", num(e.ancho, "km")], ["Forma (largo/ancho)", nf1.format(e.LB)]]) +
          `<div class="de" style="margin:8px 0 0">Supone combustible seco y continuo, terreno llano y viento constante. Usa la regla del 10 % (Cruz y Alexander, 2019), pensada para bosque y matorral (en pasto el fuego puede correr más), y la elipse de Anderson (1983). No se dibuja donde hay menos de un ${CON_COMBUSTIBLE} % de vegetación natural.</div></div>`)
        .addTo(capas.propagacion);
    }
    sincronizar();
  }

  function acciones(g) {
    const lista = [], r = RIESGO[0], nr = nivelRiesgo(r, g.lat, g.lon), rel = muestraRelieve(g.lat, g.lon);
    const cerca = D.incidencias.map((i) => ({ i, d: km(g, i) })).filter((x) => x.d <= 5).sort((a, b) => a.d - b.d)[0];
    const persistente = g.pasadas >= 3 && g.horas >= 12 && g.frp < 10;
    if (cerca) lista.push({ p: 2, t: `Cruzar con la incidencia oficial de ${cerca.i.municipio || "la zona"}`,
      r: `${cerca.i.fuente} la tiene como «${cerca.i.estado || "sin estado"}», a ${nf1.format(cerca.d)} km del foco.` });
    else if (!persistente && g.pasadas === 1) lista.push({ p: 3, t: "Confirmar con una segunda fuente",
      r: "Una sola pasada de satélite y ninguna incidencia oficial a menos de 5 km. Comprobar con la próxima pasada, cámaras o el 112." });
    if (persistente) lista.push({ p: 1, t: "Posible fuente fija: verificar antes de tratarlo como incendio",
      r: `Detectado en ${g.pasadas} pasadas durante ${nf0.format(g.horas)} h con poca potencia (máx. ${nf1.format(g.frp)} MW). Suele ser industria, vertedero o quema autorizada.` });
    const cob = g.cobertura;
    if (cob) {
      const pct = (k) => cob.fracciones_pct[k] || 0;
      if (pct("agua") >= 50) lista.push({ p: 2, t: "Probable falso positivo sobre agua",
        r: `El ${pct("agua")} % del píxel es agua: suele ser un barco, una plataforma o un reflejo.` });
      else if (pct("urbano") >= 40) lista.push({ p: 2, t: "Foco en zona urbana o industrial",
        r: `El ${pct("urbano")} % del píxel es suelo urbano: posible fuente fija (industria, vertedero) o incendio urbano, no forestal.` });
      else if (cob.dominante === "cultivo" && cob.combustible_pct < 50) lista.push({ p: 2, t: "Probable quema agrícola: verificar",
        r: `Cultivo dominante (${pct("cultivo")} %) y solo un ${cob.combustible_pct} % de vegetación natural en el píxel.` });
      else if (cob.combustible_pct >= 60) lista.push({ p: 4, t: "Vegetación natural o arbolada: posible incendio forestal",
        r: `Un ${cob.combustible_pct} % del píxel es bosque, matorral o pasto (${textoCobertura(cob)}). Ojo: el mapa de cobertura suele contar olivares y viñedos como bosque, matorral o pasto.` });
    }
    if (g.viento && (g.viento.racha_kmh || 0) >= 30) lista.push({ p: 4, t: `Vigilar el avance hacia el ${cardinal(g.viento.hacia_grados)}`,
      r: `Rachas de ${nf0.format(g.viento.racha_kmh)} km/h en el foco (modelo Open-Meteo).` });
    if (g.viento && g.viento.regla_30) lista.push({ p: 5, t: "Condiciones extremas: se cumple la regla del 30",
      r: `${num(g.viento.temperatura_c, "°C")}, ${num(g.viento.humedad_pct, "%", nf0)} de humedad y ${num(g.viento.velocidad_kmh, "km/h")} de viento.` });
    if (nr != null && nr >= 3) lista.push({ p: 4, t: `Riesgo AEMET ${NIVELES[nr].toLowerCase()} previsto`,
      r: `Previsión para el ${fdia.format(new Date(r.fecha + "T12:00:00Z"))} en este punto.` });
    if (rel && rel.pend >= 20) lista.push({ p: 3, t: `Pendiente fuerte (${nf0.format(rel.pend)}°)`,
      r: "El fuego avanza más rápido ladera arriba; la propagación dibujada no lo tiene en cuenta." });
    return lista.sort((a, b) => b.p - a.p);
  }
  function dibujarAcciones() {
    capas.acciones?.remove(); capas.acciones = L.layerGroup();
    for (const g of GRUPOS) {
      g.acciones = acciones(g);
      if (!g.acciones.length) continue;
      const html = `<div class="pop"><h4>Acciones propuestas</h4><div class="de">${lugar(g) || "Foco"} · ${g.focos.length} detecciones · ${esc(g.satelites.join(", "))}</div>` +
        `<ul class="acciones">${g.acciones.map((a) => `<li><b>${esc(a.t)}</b><span>${esc(a.r)}</span></li>`).join("")}</ul>` +
        `<div class="de" style="margin:8px 0 0">Reglas automáticas: priorizan comprobaciones, no son órdenes operativas.</div></div>`;
      const m = L.marker([g.lat, g.lon], { pane: "acciones", title: g.acciones[0].t, zIndexOffset: 500,
        icon: L.divIcon({ className: "marca-accion", iconSize: [14, 14], iconAnchor: [-6, 20], html: `<span><b>${g.acciones.length}</b></span>` }) }).bindPopup(html);
      m.addTo(capas.acciones); marcadores.set(g, m);
    }
    $("n-acciones").textContent = nf0.format(GRUPOS.filter((g) => g.acciones.length).length);
    sincronizar();
  }

  // --- Visibilidad: menú → capas ------------------------------------------------------------
  function sincronizar() {
    const vientos = $("c-vientos").checked, sat = $("c-satelites").checked;
    const ver = { firms: sat && $("c-firms").checked, seviri: sat && $("c-seviri").checked, areas: sat && $("c-areas").checked,
      aemet: vientos && $("c-aemet").checked, puertos: vientos && $("c-puertos").checked, rejilla: vientos && $("c-rejilla").checked,
      "112": $("c-112").checked, propagacion: $("c-propagacion").checked, acciones: $("c-acciones").checked };
    for (const [k, v] of Object.entries(ver)) if (capas[k]) v ? capas[k].addTo(mapa) : capas[k].remove();
    $("c-limites").checked ? capaLimites.addTo(mapa) : capaLimites.remove();
    pintarLeyenda();
    if (vista) vista.actualizar();
  }

  function pintarLeyenda() {
    const m = METRICAS[$("sel-metrica").value], partes = [];
    if ($("c-satelites").checked) partes.push(`<div class="tit">Focos por confianza</div><div class="fila"><span><i style="background:${C.alto}"></i>Alta</span><span><i style="background:${C.medio}"></i>Media</span><span><i style="background:${C.bajo}"></i>Baja</span><span><i class="cuadro" style="border:2px solid #f97316"></i>Área quemada</span></div>`);
    if ($("c-112").checked) partes.push(`<div class="tit">Incidencias 112</div><div class="fila">${Object.entries(COLOR_ESTADO).map(([e, c]) => `<span><i class="cuadro" style="background:#1b1714;border:2px solid ${c}"></i>${capital(e)}</span>`).join("")}</div>`);
    if ($("c-riesgo").checked && riesgoSel()) partes.push(`<div class="tit">Riesgo AEMET · ${esc(fsemana.format(new Date(riesgoSel().fecha + "T12:00:00Z")))}</div><div class="fila">${NIVELES.map((n, i) => `<span><i class="barra-c" style="background:${COLOR_NIVEL[i]}"></i>${n}</span>`).join("")}</div>`);
    if ($("c-cobertura").checked && COB) partes.push(`<div class="tit">Cobertura del suelo · ESA WorldCover</div><div class="fila">` +
      Object.entries(COB.clases).map(([n, c]) => `<span><i class="barra-c" style="background:${c}"></i>${esc(capital(n))}</span>`).join("") + "</div>");
    if ($("c-pendiente").checked) partes.push(`<div class="tit">Pendiente</div><div class="fila"><span><i class="barra-c" style="background:rgb(230,200,60)"></i>10–20°</span><span><i class="barra-c" style="background:rgb(240,140,40)"></i>20–30°</span><span><i class="barra-c" style="background:rgb(225,50,50)"></i>&gt; 30°</span></div>`);
    if ($("c-tintado").checked) partes.push(`<div class="tit">Altitud</div><div class="fila">${[[0, "0"], [500, "500"], [1400, "1.400"], [2000, "2.000"], [3000, "3.000 m"]].map(([h, t]) => `<span><i class="barra-c" style="background:rgb(${tinte(h).map(Math.round).join(",")})"></i>${t}</span>`).join("")}</div>`);
    if ($("c-propagacion").checked) partes.push(`<div class="fila"><span><i class="barra-c" style="background:transparent;border:1.5px dashed ${C.brasa}"></i>Propagación ilustrativa en ${$("sel-horizonte").value} h</span><span><i class="cuadro" style="background:${C.bajo};transform:rotate(45deg)"></i>Acciones</span></div>`);
    if ($("c-vientos").checked) partes.push(`<div class="tit">${esc(m.titulo)} · flecha hacia donde sopla</div><div class="fila">` +
      m.cortes.map(([, c, t]) => `<span><i class="barra-c" style="background:${c}"></i>${esc(t)}</span>`).join("") +
      `<span><i style="background:transparent;border:2px solid ${C.alto}"></i>Regla del 30</span></div>`);
    $("leyenda-cuerpo").innerHTML = partes.join("");
    $("leyenda").hidden = !partes.length;
  }

  // --- Relieve 3D (three.js, se carga solo al activarlo) -------------------------------------
  let vista = null;
  const cargarScript = (src) => new Promise((ok, ko) => { const s = document.createElement("script"); s.src = src; s.onload = ok;
    s.onerror = () => ko(new Error("No se pudo cargar " + src)); document.head.appendChild(s); });
  async function cargarThree() {
    if (!window.THREE) await cargarScript("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js");
    if (!THREE.OrbitControls) await cargarScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js");
  }

  function crearVista3D() {
    const cont = $("vista3d"), centro = mapa.getCenter(), b = mapa.getBounds();
    const z = zonaDe(centro.lat, centro.lng) || REL.peninsula;
    const fx = (lon) => (lon - z.lo0) / (z.lo1 - z.lo0) * z.W, fy = (lat) => (z.m1 - merc(lat)) / (z.m1 - z.m0) * z.H;
    let x0 = Math.max(0, Math.floor(fx(b.getWest()))), x1 = Math.min(z.W - 1, Math.ceil(fx(b.getEast())));
    let y0 = Math.max(0, Math.floor(fy(b.getNorth()))), y1 = Math.min(z.H - 1, Math.ceil(fy(b.getSouth())));
    if (x1 - x0 < 40) { const c = (x0 + x1) / 2; x0 = Math.max(0, Math.round(c - 20)); x1 = Math.min(z.W - 1, x0 + 40); }
    if (y1 - y0 < 40) { const c = (y0 + y1) / 2; y0 = Math.max(0, Math.round(c - 20)); y1 = Math.min(z.H - 1, y0 + 40); }
    const w = x1 - x0 + 1, h = y1 - y0 + 1, paso = Math.max(1, Math.ceil(Math.max(w, h) / 320));
    const cols = Math.floor((w - 1) / paso) + 1, filas_ = Math.floor((h - 1) / paso) + 1;
    const latC = Math.atan(Math.sinh(z.m1 - ((y0 + y1) / 2) / z.H * (z.m1 - z.m0))) / RAD;
    const kmPx = z.celEcuador * Math.cos(latC * RAD) / 1000;
    const anchoKm = (cols - 1) * paso * kmPx, altoKm = (filas_ - 1) * paso * kmPx;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(cont.clientWidth, cont.clientHeight);
    renderer.setClearColor(0x0e171c);
    cont.appendChild(renderer.domElement);
    const escena = new THREE.Scene();
    const camara = new THREE.PerspectiveCamera(42, cont.clientWidth / cont.clientHeight, 0.05, 20000);
    camara.up.set(0, 0, 1);
    const lado = Math.max(anchoKm, altoKm);
    camara.position.set(0, -lado * 0.95, lado * 0.62);
    const controles = new THREE.OrbitControls(camara, renderer.domElement);
    controles.target.set(0, 0, 0); controles.maxPolarAngle = Math.PI * 0.49; controles.enableDamping = !sinMovimiento;
    escena.add(new THREE.AmbientLight(0xffffff, 0.8));
    const sol = new THREE.DirectionalLight(0xffffff, 0.45); sol.position.set(-1, 1, 1.4); escena.add(sol);

    const geo = new THREE.PlaneGeometry(anchoKm, altoKm, cols - 1, filas_ - 1);
    const base = new Float32Array(cols * filas_);
    for (let r = 0; r < filas_; r++) for (let c = 0; c < cols; c++) base[r * cols + c] = Math.max(0, z.alt[(y0 + r * paso) * z.W + (x0 + c * paso)]) / 1000;
    const lienzo = document.createElement("canvas"); lienzo.width = w; lienzo.height = h;
    const textura = new THREE.CanvasTexture(lienzo);
    const malla = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: textura }));
    escena.add(malla);

    function alturas() {
      const ex = +$("r-exag").value, pos = geo.attributes.position;
      for (let i = 0; i < base.length; i++) pos.setZ(i, base[i] * ex);
      pos.needsUpdate = true; geo.computeVertexNormals();
    }
    function pintarTextura() {
      const cx = lienzo.getContext("2d");
      cx.fillStyle = "#0e171c"; cx.fillRect(0, 0, w, h);
      const fondo = z.lienzo || lienzoRelieve(z, true, true, +$("r-exag").value);
      cx.drawImage(fondo, x0, y0, w, h, 0, 0, w, h);
      // Capas en Mercator (cobertura, riesgo): se recorta la parte de la imagen que cae en la ventana.
      const lon0 = z.lo0 + x0 / z.W * (z.lo1 - z.lo0), lon1 = z.lo0 + (x1 + 1) / z.W * (z.lo1 - z.lo0);
      const mT = z.m1 - y0 / z.H * (z.m1 - z.m0), mB = z.m1 - (y1 + 1) / z.H * (z.m1 - z.m0);
      const recortar = (img, [[s, o], [n, e]], alfa) => {
        if (!img.naturalWidth) return;
        const W = img.naturalWidth, H = img.naturalHeight, mn = merc(n), ms = merc(s);
        const sx = (lon0 - o) / (e - o) * W, sx1 = (lon1 - o) / (e - o) * W, sy = (mn - mT) / (mn - ms) * H, sy1 = (mn - mB) / (mn - ms) * H;
        if (sx1 <= 0 || sx >= W || sy1 <= 0 || sy >= H) return;
        cx.globalAlpha = alfa; cx.drawImage(img, sx, sy, sx1 - sx, sy1 - sy, 0, 0, w, h); cx.globalAlpha = 1;
      };
      if ($("c-cobertura").checked) for (const c of imgsCobertura) recortar(c.img, c.limites, 0.7);
      if ($("c-pendiente").checked && z.lienzoPend) cx.drawImage(z.lienzoPend, x0, y0, w, h, 0, 0, w, h);
      const r = riesgoSel();
      if ($("c-riesgo").checked && r && r.img) recortar(r.img, r.limites, 0.6);
      const punto = (lat, lon, radio, color, borde) => { const px = fx(lon) - x0, py = fy(lat) - y0;
        if (px < 0 || py < 0 || px > w || py > h) return;
        cx.beginPath(); cx.arc(px, py, radio, 0, 2 * Math.PI); cx.fillStyle = color; cx.fill(); cx.lineWidth = 1; cx.strokeStyle = borde; cx.stroke(); };
      const rpx = Math.max(1.5, w / 260);
      if ($("c-propagacion").checked) for (const g of GRUPOS) if (g.elipse) {
        cx.beginPath(); g.elipse.pts.forEach(([la, lo], k) => { const px = fx(lo) - x0, py = fy(la) - y0; k ? cx.lineTo(px, py) : cx.moveTo(px, py); });
        cx.fillStyle = "rgba(236,138,60,.25)"; cx.fill(); cx.strokeStyle = C.brasa; cx.stroke(); }
      if ($("c-satelites").checked && $("c-areas").checked) for (const a of D.areas) punto(a.lat, a.lon, rpx * 1.3, "rgba(194,65,12,.8)", "#f97316");
      if ($("c-112").checked) for (const i of D.incidencias) punto(i.lat, i.lon, rpx * 1.6, colorEstado(i.estado), "#1b1714");
      if ($("c-satelites").checked) for (const f of D.focos) if ((ORDEN_CONF[f.conf] ?? 0) >= +$("sel-conf").value) punto(f.lat, f.lon, rpx * (1 + Math.sqrt(f.frp || 0) * 0.15), colorConf(f.conf), "#1b1714");
      textura.needsUpdate = true;
    }
    alturas(); pintarTextura();
    $("aviso3d").textContent = `Relieve 3D · ${nf0.format(anchoKm)} × ${nf0.format(altoKm)} km · exageración ×${$("r-exag").value} · arrastra para girar`;

    let vivo = true;
    (function bucle() { if (!vivo) return; controles.update(); renderer.render(escena, camara); requestAnimationFrame(bucle); })();
    const obs = new ResizeObserver(() => { renderer.setSize(cont.clientWidth, cont.clientHeight);
      camara.aspect = cont.clientWidth / Math.max(1, cont.clientHeight); camara.updateProjectionMatrix(); });
    obs.observe(cont);
    return {
      actualizar() { alturas(); pintarTextura();
        $("aviso3d").textContent = `Relieve 3D · ${nf0.format(anchoKm)} × ${nf0.format(altoKm)} km · exageración ×${$("r-exag").value} · arrastra para girar`; },
      cerrar() { vivo = false; obs.disconnect(); controles.dispose(); geo.dispose(); textura.dispose(); renderer.dispose(); renderer.domElement.remove(); },
    };
  }
  async function conmutar3D(si) {
    const cont = $("vista3d");
    if (!si) { vista?.cerrar(); vista = null; cont.hidden = true; return; }
    cont.hidden = false; $("aviso3d").textContent = "Cargando relieve 3D…";
    try { await relieveListo; await cargarThree(); if ($("c-3d").checked && !vista) vista = crearVista3D(); }
    catch (e) { $("aviso3d").textContent = "No se pudo abrir el 3D: " + e.message; }
  }

  // --- Parte de situación --------------------------------------------------------------
  let zona = "ES";
  const enZona = (p) => zona === "ES" || p.ccaa === zona;
  function cifra(valor, unidad, etiqueta, alerta) {
    return `<div class="cifra${alerta ? " alerta" : ""}"><div class="v">${valor}${unidad ? `<small>${esc(unidad)}</small>` : ""}</div><div class="e">${etiqueta}</div></div>`;
  }
  function itemLista(clave, color, l1, l2, valor) {
    return `<li><button type="button" data-i="${clave}"><span class="punto" style="background:${color}"></span>` +
      `<span class="txt"><span class="l1">${l1}</span><span class="l2">${l2}</span></span><span class="dato">${valor}</span></button></li>`;
  }
  let enlaces = [];
  const enlazar = (lista) => { enlaces.push(lista); return enlaces.length - 1; };

  function riesgoDeZona(r) {
    if (zona === "ES") return { reparto: r.reparto_pct, max: r.nivel_max };
    const reg = comunidades.find((c) => c.id === zona), cuenta = [0, 0, 0, 0, 0, 0];
    const paso = Math.max(0.02, (reg.caja[2] - reg.caja[0]) / 120);
    for (let lat = reg.caja[1]; lat <= reg.caja[3]; lat += paso) for (let lon = reg.caja[0]; lon <= reg.caja[2]; lon += paso) {
      if (!contiene(reg, lat, lon)) continue; const n = nivelRiesgo(r, lat, lon); if (n != null) cuenta[n]++; }
    const total = cuenta.reduce((a, b) => a + b, 0);
    if (!total) return null;
    return { reparto: Object.fromEntries(NIVELES.map((n, i) => [n, (100 * cuenta[i]) / total])), max: NIVELES[cuenta.map((c, i) => (c >= 3 ? i : -1)).reduce((a, b) => Math.max(a, b), 0)] };
  }

  function actualizarParte() {
    enlaces = [];
    const V = D.ventanas, focos = D.focos.filter(enZona), areas = D.areas.filter(enZona), incid = D.incidencias.filter(enZona);
    const estaciones = [...D.aemet, ...D.puertos].filter(enZona), grupos = GRUPOS.filter(enZona);
    const ha = areas.reduce((s, a) => s + (a.ha || 0), 0);
    const conViento = estaciones.filter((s) => s.racha != null);
    const maxRacha = conViento.reduce((m, s) => (!m || s.racha > m.racha ? s : m), null);
    const minHr = estaciones.filter((s) => s.hr != null).reduce((m, s) => (!m || s.hr < m.hr ? s : m), null);
    const r30 = estaciones.filter((s) => s.r30).length;
    const activas = incid.filter((i) => ["activo", "estabilizado", "controlado"].includes(i.estado)).length;
    const avisos = incid.filter((i) => i.estado === "aviso sin fase").length;
    const altas = focos.filter((f) => f.conf === "alta").length;

    $("r-titulo").textContent = zona === "ES" ? "España" : nombreCCAA[zona];
    $("r-sub").textContent = zona === "ES" ? "Península, Baleares, Canarias, Ceuta y Melilla" :
      "Las cifras cuentan solo lo que cae dentro de la comunidad; las boyas mar adentro cuentan solo para España.";
    $("cifras").innerHTML =
      cifra(nf0.format(focos.length), "", `focos de satélite en ${V.horas_focos} h · ${altas} de confianza alta`, altas > 0) +
      cifra(nf0.format(activas), "", `incendios 112 en curso${avisos ? ` · más ${avisos} ${avisos === 1 ? "aviso" : "avisos"} sin fase` : ""} · ${incid.length} en ${V.dias_incidencias} días`, activas > 0) +
      cifra(nf0.format(ha), "ha", `${areas.length} áreas quemadas publicadas en ${V.dias_effis} días`) +
      cifra(maxRacha ? nf0.format(maxRacha.racha) : "—", "km/h", maxRacha ? `racha máxima · ${esc(maxRacha.nombre)}` : "racha máxima", maxRacha && maxRacha.racha >= 50) +
      cifra(minHr ? nf0.format(minHr.hr) : "—", "%", minHr ? `humedad mínima · ${esc(minHr.nombre)}` : "humedad mínima", minHr && minHr.hr < 30) +
      cifra(nf0.format(r30), "", "estaciones en regla del 30 (>30 °C, <30 %, >30 km/h)", r30 > 0);

    // Riesgo AEMET
    const r = riesgoSel();
    $("sec-riesgo").hidden = !r;
    if (r) {
      const rz = riesgoDeZona(r);
      $("h-riesgo").textContent = fsemana.format(new Date(r.fecha + "T12:00:00Z"));
      $("riesgo-zona").innerHTML = rz ? `<div class="reparto" role="img" aria-label="Reparto del territorio por nivel de riesgo">` +
        NIVELES.map((n, i) => `<span style="width:${rz.reparto[n] || 0}%;background:${COLOR_NIVEL[i]}" title="${n}: ${nf1.format(rz.reparto[n] || 0)} %"></span>`).join("") + `</div>` +
        `<div class="subt">Nivel máximo: <strong>${esc(rz.max || "—")}</strong> · ${nf0.format(100 - (rz.reparto["Muy bajo"] || 0))} % del territorio en «bajo» o más</div>` +
        `<p class="nota">Previsión de AEMET, validez 12:00 UTC. Actívala en Capas → Riesgo.</p>` : '<p class="vacio">Sin datos de riesgo para esta zona.</p>';
    }

    // Incidencias 112
    const orden = (e) => ({ activo: 0, estabilizado: 1, controlado: 2, "aviso sin fase": 3 }[e] ?? 4);
    const li = [...incid].sort((a, b) => orden(a.estado) - orden(b.estado) || String(b.inicio_utc).localeCompare(String(a.inicio_utc))).slice(0, 8);
    const kI = enlazar(li);
    $("h-112").textContent = incid.length > li.length ? `${li.length} de ${incid.length}` : "";
    $("lista-112").innerHTML = li.length ? li.map((i, n) => itemLista(`${kI}:${n}`, colorEstado(i.estado), `${esc(i.municipio || "—")} · ${esc(capital(i.estado) || "")}`,
      `${esc(i.fuente)} · ${cuando(i.inicio_utc)}`, i.superficie_ha != null ? num(i.superficie_ha, "ha") : "")).join("") :
      `<p class="vacio">Ninguna incidencia oficial en ${V.dias_incidencias} días${zona === "ES" ? "" : " en esta comunidad"}.</p>`;

    // Acciones
    const la_ = grupos.filter((g) => g.acciones?.length).sort((a, b) => b.acciones[0].p - a.acciones[0].p || b.frp - a.frp).slice(0, 8);
    const kA = enlazar(la_);
    $("h-acciones").textContent = la_.length ? `${la_.length} focos` : "";
    $("lista-acciones").innerHTML = la_.length ? la_.map((g, n) => itemLista(`${kA}:${n}`, C.bajo, esc(g.acciones[0].t),
      `${esc(g.prov || "Sin provincia")} · ${g.acciones.length} ${g.acciones.length === 1 ? "acción" : "acciones"} · ${g.pasadas} pasadas`, num(g.frp, "MW"))).join("") :
      '<p class="vacio">Sin focos que revisar.</p>';

    // Focos, áreas, viento
    const lf = [...focos].sort((a, b) => (b.frp || 0) - (a.frp || 0)).slice(0, 8), kF = enlazar(lf);
    $("h-focos").textContent = focos.length > lf.length ? `${lf.length} de ${focos.length}` : "";
    $("lista-focos").innerHTML = lf.length ? lf.map((f, i) => itemLista(`${kF}:${i}`, colorConf(f.conf), `${esc(f.prov || "Sin provincia")} · ${esc(f.satelite)}`,
      `${cuando(f.fecha)} · ${esc(f.conf ?? "")}${f.viento ? ` · viento ${num(f.viento.velocidad_kmh, "km/h", nf0)} ${esc(f.viento.direccion_cardinal ?? "")}` : ""}`,
      num(f.frp, "MW"))).join("") : `<p class="vacio">Sin focos en la ventana de ${V.horas_focos} h.</p>`;
    const la = [...areas].sort((a, b) => (b.ha || 0) - (a.ha || 0)).slice(0, 6), kAr = enlazar(la);
    $("h-areas").textContent = areas.length > la.length ? `${la.length} de ${areas.length}` : "";
    $("lista-areas").innerHTML = la.length ? la.map((a, i) => itemLista(`${kAr}:${i}`, "#c2410c", esc(a.municipio || "—"),
      `${esc(a.provincia || "")} · ardió el ${a.fecha ? fdia.format(new Date(a.fecha)) : "—"} · ${a.novedad === "nueva" ? "nueva" : "revisada"}`,
      num(a.ha, "ha", nf0))).join("") : `<p class="vacio">EFFIS no ha publicado áreas en ${V.dias_effis} días.</p>`;
    const lv = [...conViento].sort((a, b) => b.racha - a.racha).slice(0, 6), kV = enlazar(lv);
    $("lista-viento").innerHTML = lv.length ? lv.map((s, i) => itemLista(`${kV}:${i}`, colorMetrica(METRICAS.racha, s.racha), esc(s.nombre),
      `${esc(s.fuente)} · ${edad(s.edad)} · del ${esc(s.card ?? "—")}`, num(s.racha, "km/h", nf0))).join("") : '<p class="vacio">Sin datos de viento.</p>';
  }

  function pintarFuentes() {
    const sev = (D.estado["EUMETSAT LSA-SAF (SEVIRI)"] || {}).vigilancia;
    if (sev && typeof sev === "object" && sev.pct_vigilado < 30) {
      $("aviso-seviri").hidden = false;
      $("aviso-seviri").innerHTML = `<strong>Meteosat casi ciego</strong><span>A las ${fhora.format(new Date(sev.fecha_utc))} solo pudo vigilar el ${nf1.format(sev.pct_vigilado)} % de España: ` +
        `el ${nf1.format(sev.pct_nubes)} % estaba bajo nubes. Que SEVIRI no vea focos no descarta incendios; la referencia son los focos de NASA FIRMS.</span>`;
    }
    $("lista-fuentes").innerHTML = Object.entries(D.estado).map(([nombre, e]) => {
      const extra = e.estado === "ok" ? `<span class="n">${nf0.format(e.registros)}</span>` : "<span></span>";
      let det = e.estado !== "ok" ? esc(e.detalle) : "";
      if (e.vigilancia && typeof e.vigilancia === "object") det = `vigiló el ${nf1.format(e.vigilancia.pct_vigilado)} % de España`;
      if (e.detalle_fuentes) det = Object.entries(e.detalle_fuentes).map(([k, v]) => `${esc(k)}: ${typeof v === "number" ? nf0.format(v) : esc(v)}`).join(" · ");
      return `<li><span class="chip ${esc(e.estado)}">${esc(e.estado)}</span><span>${esc(nombre)}</span>${extra}${det ? `<span class="det">${det}</span>` : ""}</li>`;
    }).join("");
  }

  // --- Controles -----------------------------------------------------------------------
  for (const r of comunidades) $("sel-region").insertAdjacentHTML("beforeend", `<option value="${esc(r.id)}">${esc(r.nombre)}</option>`);
  $("sel-region").addEventListener("change", (ev) => {
    zona = ev.target.value; resalte.clearLayers();
    const vuelo = { animate: !sinMovimiento, duration: 0.8 };
    if (zona === "ES") mapa.flyToBounds(PENINSULA, vuelo);
    else { const r = comunidades.find((c) => c.id === zona); resalte.addData(r.feature);
           mapa.flyToBounds(L.latLngBounds([r.caja[1], r.caja[0]], [r.caja[3], r.caja[2]]).pad(0.08), vuelo); }
    actualizarParte();
    if (vista) mapa.once("moveend", () => { vista.cerrar(); vista = crearVista3D(); });
  });

  const btn = $("btn-capas"), menu = $("menu-capas");
  const abrir = (si) => { menu.hidden = !si; btn.setAttribute("aria-expanded", String(si)); };
  btn.addEventListener("click", (ev) => { ev.stopPropagation(); abrir(menu.hidden); });
  document.addEventListener("click", (ev) => { if (!menu.hidden && !menu.contains(ev.target) && ev.target !== btn) abrir(false); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !menu.hidden) { abrir(false); btn.focus(); } });
  L.DomEvent.disableClickPropagation(menu); L.DomEvent.disableScrollPropagation(menu);
  // El checkbox maestro de un grupo no debe abrir/cerrar el desplegable al pulsarlo.
  for (const id of ["c-vientos", "c-satelites"]) $(id).addEventListener("click", (ev) => ev.stopPropagation());

  const al = (ids, fn, evento = "change") => [].concat(ids).forEach((id) => $(id).addEventListener(evento, fn));
  al(["c-vientos", "c-satelites", "c-firms", "c-seviri", "c-areas", "c-aemet", "c-puertos", "c-rejilla", "c-112", "c-propagacion", "c-acciones", "c-limites"], sincronizar);
  al(["c-sombreado", "c-tintado", "c-pendiente"], () => { relieveListo.then(pintarRelieve); pintarLeyenda(); });
  al(["c-riesgo", "sel-dia"], () => { pintarRiesgo(); pintarLeyenda(); actualizarParte(); dibujarAcciones(); });
  al("c-cobertura", () => { pintarCobertura(); pintarLeyenda(); });
  al("sel-conf", dibujarFocos);
  al(["sel-metrica", "sel-edad", "c-r30"], dibujarEstaciones);
  al("sel-horizonte", () => { dibujarPropagacion(); if (vista) vista.actualizar(); });
  al("c-3d", (ev) => conmutar3D(ev.target.checked));
  let espera = null;
  al("r-exag", () => { $("v-exag").textContent = "×" + $("r-exag").value; clearTimeout(espera);
    espera = setTimeout(() => relieveListo.then(pintarRelieve), 120); }, "input");

  document.querySelector(".parte").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-i]"); if (!b) return;
    const [l, i] = b.dataset.i.split(":").map(Number), dato = enlaces[l][i], m = marcadores.get(dato);
    if (vista) { $("c-3d").checked = false; conmutar3D(false); }
    mapa.flyTo([dato.lat, dato.lon], Math.max(mapa.getZoom(), 9), { animate: !sinMovimiento, duration: 0.8 });
    if (m) { if (!mapa.hasLayer(m)) m.addTo(mapa); setTimeout(() => m.openPopup(), sinMovimiento ? 0 : 850); }
  });

  const btnLeyenda = $("btn-leyenda"), plegarLeyenda = (si) => { $("leyenda-cuerpo").hidden = si; btnLeyenda.setAttribute("aria-expanded", String(!si)); };
  btnLeyenda.addEventListener("click", () => plegarLeyenda(!$("leyenda-cuerpo").hidden));
  plegarLeyenda(matchMedia("(max-width: 700px)").matches);

  // --- Arranque ------------------------------------------------------------------------
  const cuenta = (id, n) => ($(id).textContent = nf0.format(n));
  cuenta("n-firms", D.focos.filter((f) => f.sensor !== "SEVIRI").length); cuenta("n-seviri", D.focos.filter((f) => f.sensor === "SEVIRI").length);
  cuenta("n-areas", D.areas.length); cuenta("n-aemet", D.aemet.length); cuenta("n-puertos", D.puertos.length);
  cuenta("n-rejilla", D.rejilla.length); cuenta("n-r30", [...D.aemet, ...D.puertos].filter((s) => s.r30).length);
  cuenta("n-112", D.incidencias.length);
  const sin112 = (D.estado["Incidencias 112 (oficiales)"] || {}).detalle_fuentes;
  if (sin112) $("ayuda-112").textContent = "Servicios autonómicos: " + Object.keys(sin112).join(", ") + ".";
  $("sello").textContent = `Datos del ${cuando(D.generado_utc)} (hora peninsular)`;

  dibujarAreas(); dibujarIncidencias(); dibujarEstaciones(); dibujarFocos(); dibujarPropagacion();
  actualizarParte(); pintarFuentes(); pintarLeyenda();
  const relieveListo = cargarRelieve().then(pintarRelieve);
  Promise.all([relieveListo, cargarRiesgo()]).then(() => { dibujarAcciones(); actualizarParte(); })
    .catch((e) => console.error("No se pudo preparar el relieve o el riesgo:", e));
  new ResizeObserver(() => mapa.invalidateSize()).observe($("mapa"));
})();
