# Reto Incendios

Descarga (focos de calor, áreas quemadas, incidencias 112 y riesgo AEMET), guarda los datos y genera un **mapa interactivo** (`mapa_incendios.html`).

## Instalación
Puedes dejar los dos ficheros **donde quieras**: el reto busca solo tu proyecto `Incendios-V0.0/`
(la carpeta que contiene `incendios/`) en esta carpeta, sus padres y `~/Downloads/*/*/Incendios*`.
Los datos se guardan en `Incendios-V0.0/retos/output/incendios/<fecha>/`. **No hace falta `comun.py`.**

Si no lo encuentra, escribe su ruta en `RUTA_PROYECTO` (primera celda del notebook) o define `INCENDIOS_RAIZ`.

## Uso
- Notebook: abre `reto_incendios.ipynb` y ejecuta las celdas. La última abre el mapa en el navegador.
- Terminal: `python retos/reto_incendios.py`

Para regenerar solo el mapa de una carpeta ya descargada:
`from reto_incendios import mapa; mapa(carpeta, abrir=True)`

## Mapa
Se abre con doble clic (necesita internet para Leaflet y los mapas base). Menú **Capas y filtros**:
relieve (sombreado e intensidad), mapa base (oscuro, claro, calles, satélite) y filtros propios del reto.
Las listas del panel derecho son clicables y llevan al punto.
