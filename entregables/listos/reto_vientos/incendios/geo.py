"""
¿Está este punto en España? Contorno real del país, no una caja.

Contorno: Eurostat GISCO 1:1M (`datos/contorno_espana.geojson`, generado con
`herramientas/generar_contorno.py`). Incluye Baleares, Canarias, Ceuta, Melilla,
Chafarinas, Alborán y Llívia; excluye Portugal, Andorra, Gibraltar, Francia,
Marruecos y Argelia.

Aun a 1:1M la costa está simplificada, y un foco VIIRS (píxel de 375 m) en
primera línea de costa puede caer "en el mar". Regla:

    1. dentro de España                          → sí
    2. dentro de un vecino (PRT, FRA, AND, MAR, GIB, DZA) → no
    3. en ningún país (mar): sí, si España es el país más cercano y está a
       menos de `MARGEN_COSTA_KM`.

En la frontera terrestre la precisión es la de la escala 1:1M (del orden de
100 m): solo un foco prácticamente encima de la raya puede caer del lado
equivocado.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from . import config as cfg

RUTA_CONTORNO = Path(__file__).resolve().parent / "datos" / "contorno_espana.geojson"
MARGEN_COSTA_KM = 5.0
_KM_POR_GRADO = 111.32


@lru_cache(maxsize=1)
def paises() -> dict[str, list[tuple[tuple[float, float, float, float], list]]]:
    """{país: [(bbox, anillos), ...]} con la bbox de cada polígono precalculada."""
    datos = json.loads(RUTA_CONTORNO.read_text(encoding="utf-8"))
    resultado: dict = {}
    for f in datos["features"]:
        for poligono in f["geometry"]["coordinates"]:
            xs = [x for x, _ in poligono[0]]
            ys = [y for _, y in poligono[0]]
            resultado.setdefault(f["properties"]["pais"], []).append(
                ((min(xs), min(ys), max(xs), max(ys)), poligono))
    return resultado


def _en_anillo(lat: float, lon: float, anillo: list) -> bool:
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def _en_pais(lat: float, lon: float, pais: str) -> bool:
    for (o, s, e, n), poligono in paises()[pais]:
        if o <= lon <= e and s <= lat <= n and _en_anillo(lat, lon, poligono[0]) \
                and not any(_en_anillo(lat, lon, hueco) for hueco in poligono[1:]):
            return True
    return False


def _distancia_km(lat: float, lon: float, pais: str) -> float:
    """Distancia aproximada (equirectangular) del punto al borde del país."""
    kx = _KM_POR_GRADO * math.cos(math.radians(lat))
    ky = _KM_POR_GRADO
    margen = MARGEN_COSTA_KM / ky * 2     # descarta polígonos lejanos por bbox
    mejor = math.inf
    for (o, s, e, n), poligono in paises()[pais]:
        if not (o - margen <= lon <= e + margen and s - margen <= lat <= n + margen):
            continue
        for anillo in poligono:
            for (x1, y1), (x2, y2) in zip(anillo, anillo[1:]):
                ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
                bx, by = (x2 - lon) * kx, (y2 - lat) * ky
                dx, dy = bx - ax, by - ay
                t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
                mejor = min(mejor, math.hypot(ax + t * dx, ay + t * dy))
    return mejor


def en_espana(lat: float, lon: float) -> bool:
    if not any(o <= lon <= e and s <= lat <= n for o, s, e, n in cfg.BBOXES_ESPANA):
        return False
    if _en_pais(lat, lon, "ESP"):
        return True
    vecinos = [p for p in paises() if p != "ESP"]
    if any(_en_pais(lat, lon, p) for p in vecinos):
        return False
    d_espana = _distancia_km(lat, lon, "ESP")
    return d_espana <= MARGEN_COSTA_KM and all(d_espana <= _distancia_km(lat, lon, p) for p in vecinos)
