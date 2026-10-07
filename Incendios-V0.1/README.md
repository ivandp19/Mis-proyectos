# Incendios V0.0 — crawling de satélites y viento

Recoge focos de calor por satélite, áreas quemadas y viento **solo de España**, y los deja en GeoJSON con un esquema común. Todo el crawling se hace con **crawl4ai**.

**Notebook (recomendado):** abre [`pipeline_incendios.ipynb`](pipeline_incendios.ipynb) y ejecuta todo con *Run All*:
1. En la sección 1 pegas tus claves.
2. En la sección 2 se comprueba que funcionan.
3. Las secciones 4 y 5 recorren cada fuente paso a paso, con tablas.
4. La sección 6 guarda los datos y genera `visor.html`.
5. La sección 7 comprueba, fuente por fuente, que el visor contiene exactamente lo que acaba de sacar el cuaderno.
6. La sección 8 abre el visor en el navegador. Con `ABRIR_VISOR = False` solo muestra la ruta.

**Terminal:** hace lo mismo sin mostrar los pasos:

```bash
pip install -r requirements.txt
cp .env.example .env        # opcional: claves para más fuentes
python crawl.py             # satélites + viento → output/<marca UTC>/
python crawl.py --abrir     # lo mismo, y abre el visor al terminar
```

Sin ninguna clave ya funcionan FIRMS, EFFIS y Open-Meteo. Con claves se añaden AEMET (estaciones reales) y SEVIRI (detección cada 15 min).

**Retos por separado:** en [`retos/`](retos/README.md) hay dos notebooks independientes del pipeline:
- [`reto_incendios.ipynb`](retos/reto_incendios.ipynb)
- [`reto_vientos.ipynb`](retos/reto_vientos.ipynb)

Cada uno tiene dos pasos (crawling y datos) y solo produce ficheros GeoJSON y JSON, sin mapa. Para verlos en el mapa está el pipeline.

## Cómo se usa crawl4ai

Todas las peticiones pasan por [`incendios/red.py`](incendios/red.py), que usa `AsyncWebCrawler` con la estrategia HTTP de crawl4ai (`AsyncHTTPCrawlerStrategy`). No se abre navegador porque todas las fuentes son APIs o listados de directorios. Las fuentes se lanzan en paralelo y un crawl completo tarda unos 10 s. En `red.py` está documentado cómo se resuelven tres particularidades de crawl4ai:
- **Cabeceras:** se fijan por sesión, no por petición.
- **Respuestas que no son HTML:** crawl4ai las guarda en disco; se leen y se borran.
- **Errores HTTP:** llegan como texto en `error_message` y el código se extrae de ahí.

## Solo España

Los focos se filtran con el contorno real del país ([`incendios/geo.py`](incendios/geo.py)), no con una caja. El contorno viene de Eurostat GISCO a escala 1:1 millón (© EuroGeographics) y está en `incendios/datos/`; se regenera con `python herramientas/generar_contorno.py`.

- **Incluye:** península, Baleares, Canarias, Ceuta, Melilla, Chafarinas, Alborán y Llívia.
- **Excluye:** Portugal, Francia, Andorra, Gibraltar, Marruecos y Argelia.

La costa del contorno está simplificada. Un foco que cae en el mar se asigna a España si su costa es la más cercana y está a menos de 5 km.

EFFIS ya se pide con `country=ES`. Las estaciones de AEMET y las capitales de Open-Meteo están todas en España.

## Fuentes

### Satélites

| Fuente | Qué da | Frecuencia | Clave | Módulo |
|---|---|---|---|---|
| **NASA FIRMS** · VIIRS (Suomi NPP, NOAA-20, NOAA-21) | focos de calor, 375 m | 2 pasadas/día por satélite | no (opcional `FIRMS_MAP_KEY`) | `satelites/firms.py` |
| **NASA FIRMS** · MODIS (Aqua, Terra) | focos de calor, 1 km | idem | no | `satelites/firms.py` |
| **EUMETSAT LSA-SAF** · SEVIRI (Meteosat) | focos de calor, ~3–5 km | **cada 15 min**, 24 h | `LSASAF_USER/PASSWORD` (gratis) | `satelites/lsasaf.py` |
| **EFFIS** (Copernicus) | perímetros de área quemada (ha, provincia, cubierta) | diaria, con días de retraso | no | `satelites/effis.py` |

Son las mismas fuentes que usa incendiosespaña.es (lo dice su página de metodología). Aquí se va directamente a la fuente original en vez de rastrear esa web: así no dependes de un agregador privado y tienes el dato sin procesar.

VIIRS/MODIS van en órbita polar: entre pasadas el dato puede tener 1–2 h de retraso. SEVIRI es geoestacionario y cubre esos huecos, aunque con peor resolución.

### Cobertura del suelo

| Fuente | Qué da | Clave | Módulo |
|---|---|---|---|
| **ESA WorldCover 2021** (10 m, CC BY 4.0) | qué hay alrededor de cada foco e incidencia: bosque, matorral, pasto, cultivo, urbano, agua… | no | `cobertura.py` |

- **Se descarga una sola vez:** `python herramientas/generar_cobertura.py` baja las 23 teselas que tocan España (~1,4 GB, con crawl4ai). Las resume en una rejilla de ≈ 90 m con la cobertura dominante, recortada a España (`incendios/datos/cobertura_*.tif`). A partir de ahí la consulta es local, sin red.
- **Para cada foco** se mira una ventana del tamaño del píxel del satélite (~375 m en VIIRS, ~1 km en MODIS) y se guarda el reparto en `cobertura`.
- **Las Acciones** la usan para señalar probables quemas agrícolas, fuentes urbanas o industriales y falsos positivos sobre agua frente a vegetación forestal.
- **La Propagación** solo se dibuja donde hay al menos un 30 % de vegetación natural.
- **Limitación:** en el Mediterráneo WorldCover confunde los cultivos leñosos con vegetación natural (el olivar de Jaén sale como bosque y el viñedo manchego como matorral o pasto), y en 2021 varios embalses bajos salen como pasto. Por eso «cultivo» es fiable sobre todo para cereal y regadío, y la Acción correspondiente lo advierte.
- **Por qué no el Mapa Forestal de España (MFE25):** es más detallado (distingue especies), pero no se puede automatizar. Su servicio WMS está caído y las descargas exigen una verificación anti-bots (ALTCHA) en el navegador.

### Viento — arquitectura en tres capas

| Capa | Fuente | Qué da | Clave | Módulo |
|---|---|---|---|---|
| Nacional (observación) | **AEMET OpenData**, observación convencional | ~855 estaciones (~750 con anemómetro): velocidad, dirección, racha, T, HR | `AEMET_API_KEY` (gratis) | `viento/aemet.py` |
| Costa y mar (observación) | **Puertos del Estado** (red de la app iMar, API de PORTUS) | ~100 boyas, mareógrafos y estaciones de puerto españolas | no | `viento/puertos.py` |
| Nacional (respaldo) | **Open-Meteo** | modelo en las 52 capitales de provincia | no | `viento/openmeteo.py` |
| Emergencia | **Open-Meteo** en cada foco | viento en la celda de ~10 km de cada foco satelital | no | `viento/openmeteo.py` |

Cada lectura de viento incluye:
- `direccion_grados`: de dónde viene, según la convención meteorológica.
- `hacia_grados`: hacia dónde empuja el fuego.
- `regla_30`: indica si se cumplen >30 °C, <30 % de humedad y >30 km/h.
- `antiguedad_min`: minutos desde la medida. No se descarta ninguna estación por ir atrasada; esta columna dice cuánto fiarse.

### Evaluadas y no incluidas

| Fuente | Motivo |
|---|---|
| **Visor ALCIF (AEMET)** | Comprobado el 6/10/2026: https://alcif.aemet.es pide usuario y contraseña. Es un visor restringido a los servicios de extinción y el acceso se solicita a alcif@aemet.es. Mientras tanto, la capa de "viento en cada foco" ofrece algo parecido con datos abiertos. Si consigues acceso institucional, es la primera mejora. |
| **EARM / INFOCA (Andalucía)** | Comprobado el 6/10/2026: la Junta (REDIAM, subsistema CLIMA) solo publica resúmenes diarios por provincia con 2 días de retraso, sin viento en tiempo real. Los datos de 10 minutos de la red de incendios no son públicos y habría que pedirlos a la Consejería. |
| **Bseed WATCH** | Plataforma comercial (Hispasat): los sensores envían a su nube privada y los datos son solo para sus clientes. |
| **Drones con anemómetro** | Pruebas operativas del INFOCA, sin datos publicados. |
| **Scraper de Apify para AEMET** | No hace falta: AEMET OpenData es oficial, gratuito y ya está integrado. |

## Visor interactivo

Cada ejecución genera `output/<marca>/visor.html`, un mapa interactivo que se abre con doble clic. El menú **Capas** tiene estas opciones, en este orden:

| Opción | Qué hace | Datos |
|---|---|---|
| Relieve 3D | Vista tridimensional de la zona del mapa (three.js) | AWS Terrain Tiles |
| Sombreado | Relieve iluminado desde el noroeste | AWS Terrain Tiles |
| Tintado | Colores por altitud | AWS Terrain Tiles |
| Pendiente | Laderas de más de 10° | calculada del relieve |
| Cobertura del suelo | Bosque, matorral, pasto, cultivo, urbano, agua… en celdas de ≈ 370 m | ESA WorldCover 2021 |
| Límites | Comunidades autónomas y provincias | Eurostat GISCO |
| Riesgo | Previsión oficial del riesgo meteorológico de incendio (mañana, pasado y el día siguiente) | AEMET, mapa georreferenciado |
| Incidencias 112 | Incendios declarados por los servicios autonómicos | INFOCA, FIDIAS, Bombers, INFORCYL |
| Propagación | Elipse de avance con el viento actual en cada foco (1, 3 o 6 h). Ilustrativa | regla del 10 % y elipse de Anderson |
| Acciones | Comprobaciones propuestas por foco (confirmar, cruzar con el 112, vigilar el viento, pendiente, riesgo…) | reglas sobre los datos |
| Exageración | Multiplica las alturas del sombreado y del 3D | — |
| Vientos | Submenú: AEMET, Puertos del Estado y Open-Meteo, colorear por, antigüedad y regla del 30 | — |
| Satélites | Submenú: FIRMS, SEVIRI, EFFIS y confianza mínima | — |

Además hay un selector de comunidad autónoma, que acerca el mapa y recalcula el parte lateral, y fichas de detalle al hacer clic en cualquier elemento.

- **Propagación y Acciones son orientativas.** No son una simulación ni órdenes operativas, y la página lo indica en cada ficha.
- **No hay mapa base de teselas.** El artifact no puede cargarlas, así que el fondo son los límites GISCO y el relieve va incrustado en la página.
- **Es una foto de la ejecución.** Los datos van incrustados; no es un mapa en directo.
- **Publicación como artifact:** se usa `output/visor_publicar.html`, que es la misma página.

Los datos fijos se regeneran con los scripts de `herramientas/`:
- `generar_contorno.py`
- `generar_regiones.py`
- `generar_relieve.py`

## Salida

`output/<AAAAMMDDTHHMMSSZ>/`:

- `focos.geojson`: FIRMS y SEVIRI ordenados del más reciente al más antiguo. Cada foco incluye `viento_local`. Campos: `fuente, sensor, satelite, lat, lon, fecha_utc, confianza (alta/media/baja), confianza_bruta, frp_mw, dia_noche, resolucion_m`.
- `areas_quemadas.geojson`: polígonos de EFFIS publicados o actualizados en la ventana. Se filtra por `lastupdate`, no por fecha del incendio, porque EFFIS cartografía con días de retraso y sigue corrigiendo perímetros. El campo `novedad` indica si el área es `nueva` o `actualizada`.
- `viento_estaciones.geojson` / `viento_puertos.geojson` / `viento_rejilla.geojson`: lecturas de viento (AEMET / Puertos del Estado / Open-Meteo).
- `incidencias_oficiales.geojson`: incidencias 112 de INFOCA, FIDIAS, Bombers e INFORCYL.
- `visor.html`: el mapa interactivo descrito arriba.
- `estado_fuentes.json`: estado de cada fuente (`ok`, `omitida` u `error`), con número de registros y tiempo.

## Opciones

```bash
python crawl.py satelites --horas 48     # focos FIRMS de 48 h (24h / 48h / 7d sin clave)
python crawl.py viento
python crawl.py --horas-seviri 6 --dias-effis 14 --sin-viento-focos
```

## Limitaciones conocidas

- **Precisión del contorno en la frontera.** Es del orden de 100 m (escala 1:1M): solo un foco prácticamente encima de la raya podría caer del lado equivocado. Comprobado con 27 puntos de frontera y costa y con las 748 estaciones reales de AEMET: todas aciertan.
- **SEVIRI no ve a través de las nubes.** Verificado con ficheros reales: el 5/10 a las 15:15 UTC un incendio de ~650 MW en Badajoz detectado por MODIS no aparece en SEVIRI porque esos píxeles estaban clasificados como nube. Por eso cada ejecución mide qué porcentaje de España pudo vigilar (`vigilancia` en `estado_fuentes.json`). Con poca cobertura, "0 focos" no descarta incendios. `lsasaf.diagnosticar()` vuelca el contenido del último fichero si hay que investigar.
- **Open-Meteo es un modelo, no una medición.** Si hay una estación de AEMET cerca, su dato es mejor.
