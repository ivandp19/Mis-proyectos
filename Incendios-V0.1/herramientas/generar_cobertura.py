#!/usr/bin/env python3
"""
Genera la cobertura del suelo del proyecto (`incendios/datos/cobertura_*.tif` y
`cobertura.json`) a partir de ESA WorldCover 2021 v200 (10 m, CC BY 4.0).
Se ejecuta una vez: el resultado va en `incendios/datos/` y el pipeline lo
consulta sin conexión.

1. Descarga con crawl4ai las 23 teselas (3° × 3°) que tocan España: ~1,4 GB.
   Quedan en `output/cache_worldcover/` (ignorada por git) para no repetir
   descargas; `--borrar-cache` la vacía al terminar.
2. Resume cada bloque de 10 × 10 píxeles (≈ 90 m) en su cobertura dominante y
   recorta a España (contorno GISCO). Dos rejillas en grados (EPSG:4326),
   alineadas con las teselas: península + Baleares + Ceuta y Melilla, y Canarias.

    python herramientas/generar_cobertura.py
    python herramientas/generar_cobertura.py --borrar-cache
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from incendios import config as cfg  # noqa: E402
from incendios.geo import paises  # noqa: E402
from incendios.red import sesion  # noqa: E402

URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{}_Map.tif"
CACHE = cfg.RAIZ / "output" / "cache_worldcover"
DATOS = cfg.RAIZ / "incendios" / "datos"
PX_GRADO = 12000                 # WorldCover: 1/12000° por píxel
BLOQUE = 10                      # 10 × 10 píxeles → una celda de salida (1/1200° ≈ 90 m)
CELDAS_GRADO = PX_GRADO // BLOQUE
# Valores de WorldCover (0 = sin dato). El índice en esta tupla es la posición de conteo.
VALORES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
ZONAS = {"peninsula": cfg.BBOX_PENINSULA_BALEARES, "canarias": cfg.BBOX_CANARIAS}


def _nombre(la: int, lo: int) -> str:
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


def teselas_espana() -> list[tuple[int, int]]:
    """Esquinas SO de las teselas de 3° que tocan algún polígono de España."""
    teselas = set()
    for (o, s, e, n), _ in paises()["ESP"]:
        for la in range(int(s // 3 * 3), int(n // 3 * 3) + 1, 3):
            for lo in range(int(o // 3 * 3), int(e // 3 * 3) + 1, 3):
                teselas.add((la, lo))
    return sorted(teselas)


async def descargar(teselas) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    pendientes = [t for t in teselas if not (CACHE / f"{_nombre(*t)}.tif").exists()]
    print(f"Teselas: {len(teselas)} · en caché: {len(teselas) - len(pendientes)} · a descargar: {len(pendientes)}")
    async with sesion(timeout_s=900) as s:
        for i, (la, lo) in enumerate(pendientes, 1):
            t0, nombre = time.monotonic(), _nombre(la, lo)
            contenido = (await s.get(URL.format(nombre))).contenido
            if contenido[:4] not in (b"II*\x00", b"MM\x00*"):
                raise RuntimeError(f"{nombre}: la respuesta no es un GeoTIFF")
            parcial = CACHE / f"{nombre}.tif.parcial"
            parcial.write_bytes(contenido)
            parcial.rename(CACHE / f"{nombre}.tif")       # sin ficheros a medias en la caché
            print(f"  [{i}/{len(pendientes)}] {nombre}: {len(contenido) / 1e6:.0f} MB en {time.monotonic() - t0:.0f} s")


def _dominante(bloque_px: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """(h, w) píxeles WorldCover → (h/10, w/10) con el valor dominante de cada bloque."""
    h, w = bloque_px.shape[0] // BLOQUE, bloque_px.shape[1] // BLOQUE
    idx = lut[bloque_px[:h * BLOQUE, :w * BLOQUE]].reshape(h, BLOQUE, w, BLOQUE)
    cuenta = np.stack([(idx == k).sum(axis=(1, 3), dtype=np.uint8) for k in range(1, len(VALORES) + 1)])
    dominante = np.array(VALORES, dtype=np.uint8)[cuenta.argmax(axis=0)]
    dominante[cuenta.max(axis=0) == 0] = 0            # bloque entero sin dato
    return dominante


def generar_zona(nombre_zona: str, bbox, teselas) -> Path:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    o, s, e, n = bbox
    ancho, alto = round((e - o) * CELDAS_GRADO), round((n - s) * CELDAS_GRADO)
    salida = np.zeros((alto, ancho), dtype=np.uint8)
    lut = np.zeros(256, dtype=np.uint8)
    for k, v in enumerate(VALORES, 1):
        lut[v] = k

    for la, lo in teselas:
        if lo + 3 <= o or lo >= e or la + 3 <= s or la >= n:
            continue
        # Intersección tesela ∩ zona, en celdas de salida (todo alineado a 1/1200°).
        c0, c1 = max(lo, o), min(lo + 3, e)
        f0, f1 = max(la, s), min(la + 3, n)
        col_sal, fila_sal = round((c0 - o) * CELDAS_GRADO), round((n - f1) * CELDAS_GRADO)
        col_tes, fila_tes = round((c0 - lo) * PX_GRADO), round((la + 3 - f1) * PX_GRADO)
        ancho_px, alto_px = round((c1 - c0) * PX_GRADO), round((f1 - f0) * PX_GRADO)
        with rasterio.open(CACHE / f"{_nombre(la, lo)}.tif") as src:
            paso = 1200                               # 1200 filas de píxeles por lectura (~40 MB)
            for df in range(0, alto_px, paso):
                filas = min(paso, alto_px - df)
                px = src.read(1, window=((fila_tes + df, fila_tes + df + filas), (col_tes, col_tes + ancho_px)))
                d = _dominante(px, lut)
                f = fila_sal + df // BLOQUE
                salida[f:f + d.shape[0], col_sal:col_sal + d.shape[1]] = d

    # Solo España (contorno GISCO, incluidas las celdas que tocan la costa).
    transform = from_origin(o, n, 1 / CELDAS_GRADO, 1 / CELDAS_GRADO)
    poligonos = [{"type": "Polygon", "coordinates": p} for (bo, bs, be, bn), p in paises()["ESP"]
                 if be >= o and bo <= e and bn >= s and bs <= n]
    espana = rasterize(poligonos, out_shape=salida.shape, transform=transform, fill=0, default_value=1,
                       all_touched=True, dtype="uint8")
    salida[espana == 0] = 0

    ruta = DATOS / f"cobertura_{nombre_zona}.tif"
    with rasterio.open(ruta, "w", driver="GTiff", width=ancho, height=alto, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=transform, nodata=0, compress="deflate", predictor=1,
                       tiled=True, blockxsize=512, blockysize=512) as dst:
        dst.write(salida, 1)
    print(f"  {ruta.name}: {ancho} × {alto} celdas · {ruta.stat().st_size / 1e6:.1f} MB")
    return ruta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--borrar-cache", action="store_true", help="borrar las teselas descargadas al terminar")
    args = ap.parse_args()
    teselas = teselas_espana()
    asyncio.run(descargar(teselas))
    print("Procesando…")
    for zona, bbox in ZONAS.items():
        generar_zona(zona, bbox, teselas)
    (DATOS / "cobertura.json").write_text(json.dumps({
        "fuente": "ESA WorldCover 10 m 2021 v200 (© ESA WorldCover project 2021 / Contains modified Copernicus "
                  "Sentinel data (2021) processed by ESA WorldCover consortium), CC BY 4.0",
        "resolucion": f"1/{CELDAS_GRADO}° (bloques de {BLOQUE}×{BLOQUE} píxeles de 10 m, cobertura dominante)",
        "crs": "EPSG:4326", "zonas": {z: f"cobertura_{z}.tif" for z in ZONAS}, "teselas": [_nombre(*t) for t in teselas],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.borrar_cache:
        shutil.rmtree(CACHE, ignore_errors=True)
        print("Caché borrada.")


if __name__ == "__main__":
    main()
