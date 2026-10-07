#!/usr/bin/env python3
"""
Genera `incendios/datos/contorno_espana.geojson` a partir de Eurostat GISCO
(países, escala 1:1 millón, 2020). Se ejecuta una vez; el resultado va
versionado y el crawler no vuelve a descargarlo.

Por qué GISCO y no Natural Earth: "Natural Earth 10m" es escala 1:10 MILLONES,
y con ella estaciones de AEMET españolas en plena raya (aeropuerto de San
Sebastián, Valcarlos, Melilla) caían en Francia o Marruecos. A 1:1M aciertan.

Guarda España y sus vecinos (Portugal, Francia, Andorra, Marruecos, Gibraltar,
Argelia —cuya costa entra en la caja de búsqueda—) recortados a la zona de
trabajo: los vecinos sirven para decidir de quién es un foco costero que cae
fuera de la línea de costa (ver `geo.py`).

Licencia: © EuroGeographics para los límites administrativos (atribución).

    python herramientas/generar_contorno.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from incendios.red import sesion  # noqa: E402

URL = "https://gisco-services.ec.europa.eu/distribution/v2/countries/distribution/{}-region-01m-4326-2020.geojson"
# GISCO usa códigos ISO de 2 letras; `geo.py` trabaja con los de 3.
PAISES = {"ES": "ESP", "PT": "PRT", "FR": "FRA", "AD": "AND", "MA": "MAR", "GI": "GIB", "DZ": "DZA"}
ZONA = (-19.0, 27.0, 5.5, 44.5)   # oeste, sur, este, norte: península + Canarias
DESTINO = Path(__file__).resolve().parent.parent / "incendios" / "datos" / "contorno_espana.geojson"


def _en_zona(poligono) -> bool:
    xs = [p[0] for p in poligono[0]]
    ys = [p[1] for p in poligono[0]]
    o, s, e, n = ZONA
    return max(xs) >= o and min(xs) <= e and max(ys) >= s and min(ys) <= n


async def main() -> None:
    features = []
    async with sesion() as s:
        for iso2, iso3 in PAISES.items():
            poligonos = []
            for f in (await s.get(URL.format(iso2))).json()["features"]:
                g = f["geometry"]
                poligonos += g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            poligonos = [[[[round(p[0], 5), round(p[1], 5)] for p in anillo] for anillo in pol]
                         for pol in poligonos if _en_zona(pol)]
            features.append({"type": "Feature", "properties": {"pais": iso3},
                             "geometry": {"type": "MultiPolygon", "coordinates": poligonos}})
    DESTINO.write_text(json.dumps({
        "type": "FeatureCollection",
        "fuente": "Eurostat GISCO, países 1:1M 2020 (© EuroGeographics), " + URL.format("XX"),
        "features": features,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"{DESTINO} ({DESTINO.stat().st_size // 1024} KB, países: {[f['properties']['pais'] for f in features]})")


if __name__ == "__main__":
    asyncio.run(main())
