# Reto Incendios

Descarga (focos de calor, áreas quemadas, incidencias 112 y riesgo AEMET), guarda los datos y genera un **mapa interactivo** (`mapa_incendios.html`).

## Instalación
Copia `reto_incendios.py` y `reto_incendios.ipynb` dentro de la carpeta `retos/` de tu proyecto `Incendios-V0.0/`
(junto al paquete `incendios/`). Sobrescribe los anteriores. **No hace falta `comun.py`.**

## Uso
- Notebook: abre `reto_incendios.ipynb` y ejecuta las celdas. La última abre el mapa en el navegador.
- Terminal: `python retos/reto_incendios.py`

Los datos y el mapa quedan en `retos/output/incendios/<fecha>/`.
Para regenerar solo el mapa de una carpeta ya descargada:
`from reto_incendios import mapa; mapa(carpeta, abrir=True)`

## Mapa
Se abre con doble clic (necesita internet para Leaflet y los mapas base). Menú **Capas y filtros**:
relieve (sombreado e intensidad), mapa base (oscuro, claro, calles, satélite) y filtros propios del reto.
Las listas del panel derecho son clicables y llevan al punto.
