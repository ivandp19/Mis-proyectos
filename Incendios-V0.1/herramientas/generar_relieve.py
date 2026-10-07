#!/usr/bin/env python3
"""
Genera el modelo de elevación del visor (`incendios/datos/relieve_*.png` y
`relieve.json`) a partir de AWS Terrain Tiles (formato "terrarium", fuentes
SRTM/GMTED/ETOPO1, © Mapzen y colaboradores). Se ejecuta una vez.

Las teselas ya vienen en Web Mercator, la misma proyección que usa Leaflet, así
que el mosaico recortado se superpone sin reproyectar. Cada píxel codifica la
altura en metros como R·256 + G + B/256 − 32768; el visor la decodifica en el
navegador para calcular sombreado, tintado hipsométrico, pendiente y relieve 3D.

    python herramientas/generar_relieve.py
"""
from __future__ import annotations

import asyncio
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from incendios.red import sesion  # noqa: E402

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DATOS = Path(__file__).resolve().parent.parent / "incendios" / "datos"
# nombre: (oeste, sur, este, norte, zoom). Zoom 7 ≈ 1 km/píxel a estas latitudes.
ZONAS = {"peninsula": (-9.9, 35.0, 4.7, 44.2, 7), "canarias": (-18.3, 27.5, -13.2, 29.6, 8)}


def _px(lon, lat, z):
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _lonlat(x, y, z):
    n = 256 * 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def _aligerar(imagen: Image.Image) -> Image.Image:
    """
    Redondea a metros enteros (canal B a 0) y pone el mar a 0 m: el visor no
    usa batimetría, y así el PNG pesa la mitad.
    """
    import numpy as np

    a = np.asarray(imagen).astype(np.int32)
    altura = np.clip(np.round(a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768), 0, None).astype(np.int32) + 32768
    salida = np.stack([altura // 256, altura % 256, np.zeros_like(altura)], axis=-1).astype(np.uint8)
    return Image.fromarray(salida, "RGB")


async def main() -> None:
    meta = {"fuente": "AWS Terrain Tiles (terrarium; SRTM, GMTED, ETOPO1 — © Mapzen y colaboradores)",
            "codificacion": "altura_m = R*256 + G - 32768 (metros enteros; mar = 0)", "zonas": {}}
    async with sesion() as s:
        for nombre, (o, su, e, no, z) in ZONAS.items():
            x0, y0 = _px(o, no, z)
            x1, y1 = _px(e, su, z)
            tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
            mosaico = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    teja = Image.open(io.BytesIO((await s.get(URL.format(z=z, x=tx, y=ty))).contenido)).convert("RGB")
                    mosaico.paste(teja, ((tx - tx0) * 256, (ty - ty0) * 256))
            cx0, cy0, cx1, cy1 = int(x0) - tx0 * 256, int(y0) - ty0 * 256, int(x1) - tx0 * 256, int(y1) - ty0 * 256
            recorte = _aligerar(mosaico.crop((cx0, cy0, cx1, cy1)))
            ruta = DATOS / f"relieve_{nombre}.png"
            recorte.save(ruta, optimize=True)
            (lo0, la1), (lo1, la0) = _lonlat(int(x0), int(y0), z), _lonlat(int(x1), int(y1), z)
            meta["zonas"][nombre] = {"fichero": ruta.name, "ancho": recorte.width, "alto": recorte.height,
                                     "limites": [[round(la0, 5), round(lo0, 5)], [round(la1, 5), round(lo1, 5)]],
                                     "metros_por_pixel": round(40075016 * math.cos(math.radians((su + no) / 2)) / (256 * 2 ** z))}
            print(f"{ruta.name}: {recorte.size}, {ruta.stat().st_size // 1024} KB, "
                  f"{meta['zonas'][nombre]['metros_por_pixel']} m/píxel")
    (DATOS / "relieve.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
