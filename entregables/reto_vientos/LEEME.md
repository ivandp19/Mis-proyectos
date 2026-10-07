# Reto Vientos

Descarga (viento de AEMET, Puertos del Estado y Open-Meteo), guarda los datos y genera un **mapa interactivo** (`mapa_vientos.html`).

## Instalación
Copia `reto_vientos.py` y `reto_vientos.ipynb` dentro de la carpeta `retos/` de tu proyecto `Incendios-V0.0/`
(junto al paquete `incendios/`). Sobrescribe los anteriores. **No hace falta `comun.py`.**

## Uso
- Notebook: abre `reto_vientos.ipynb` y ejecuta las celdas. La última abre el mapa en el navegador.
- Terminal: `python retos/reto_vientos.py`

Los datos y el mapa quedan en `retos/output/vientos/<fecha>/`.
Para regenerar solo el mapa de una carpeta ya descargada:
`from reto_vientos import mapa; mapa(carpeta, abrir=True)`

## Mapa
Se abre con doble clic (necesita internet para Leaflet y los mapas base). Menú **Capas y filtros**:
relieve (sombreado e intensidad), mapa base (oscuro, claro, calles, satélite) y filtros propios del reto.
Las listas del panel derecho son clicables y llevan al punto.
