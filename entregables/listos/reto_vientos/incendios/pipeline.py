"""
Piezas del pipeline compartidas por `crawl.py` (terminal) y
`pipeline_incendios.ipynb` (notebook): ejecutar una fuente aislada, pasar a
GeoJSON, guardar y resumir el estado de las fuentes.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from .red import FuenteOmitida


async def ejecutar(estado: dict, nombre: str, corrutina) -> list:
    """
    Ejecuta una fuente y anota en `estado` si fue ok / omitida / error. Nunca
    lanza: una fuente caída no tumba el pipeline, devuelve [].
    """
    t0 = time.monotonic()
    try:
        resultado = await corrutina
    except FuenteOmitida as e:
        estado[nombre] = {"estado": "omitida", "detalle": str(e)}
        return []
    except Exception as e:
        estado[nombre] = {"estado": "error", "detalle": f"{type(e).__name__}: {e}"}
        return []
    estado[nombre] = {"estado": "ok", "registros": len(resultado),
                      "segundos": round(time.monotonic() - t0, 1)}
    return resultado


async def ejecutar_con_detalle(estado: dict, nombre: str, corrutina, clave: str = "detalle_fuentes") -> list:
    """Como `ejecutar`, para fuentes que devuelven (lista, detalle por subfuente)."""
    detalle: dict = {}

    async def solo_lista():
        lista, d = await corrutina
        detalle.update(d)
        return lista

    resultado = await ejecutar(estado, nombre, solo_lista())
    if detalle:
        estado[nombre][clave] = detalle
    return resultado


async def anotar(estado: dict, nombre: str, clave: str, corrutina) -> None:
    """Añade un dato complementario a una fuente ya ejecutada, sin lanzar nunca."""
    try:
        valor = await corrutina
    except FuenteOmitida:
        return
    except Exception as e:
        valor = f"error: {type(e).__name__}: {e}"
    estado.setdefault(nombre, {})[clave] = valor


def a_geojson(registros: list[dict], geometria=None) -> dict:
    features = []
    for r in registros:
        props = {k: v for k, v in r.items() if k != "geometria"}
        geom = (geometria(r) if geometria else None) or {"type": "Point", "coordinates": [r["lon"], r["lat"]]}
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def nueva_salida() -> Path:
    directorio = cfg.DIR_SALIDA / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directorio.mkdir(parents=True, exist_ok=True)
    return directorio


def guardar(directorio: Path, nombre: str, contenido) -> Path:
    ruta = directorio / nombre
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def resumen(estado: dict) -> str:
    lineas = []
    for nombre, e in estado.items():
        extra = f"{e['registros']:>6} registros  {e['segundos']:>5}s" if e["estado"] == "ok" else e["detalle"]
        lineas.append(f"  {e['estado']:<8} {nombre:<32} {extra}")
        v = e.get("vigilancia")
        if isinstance(v, dict):
            lineas.append(f"  {'':<8} {'':<32} vigiló el {v['pct_vigilado']}% de España "
                          f"({v['pct_nubes']}% bajo nubes, {v['fecha_utc'][11:16]} UTC)")
        elif v:
            lineas.append(f"  {'':<8} {'':<32} vigilancia: {v}")
    return "\n".join(lineas)
