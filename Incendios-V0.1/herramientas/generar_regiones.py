#!/usr/bin/env python3
"""
Genera `incendios/datos/regiones_espana.geojson`: comunidades autónomas (NUTS 2)
y provincias (NUTS 3; en Baleares y Canarias son islas o grupos de islas) a
partir de Eurostat GISCO, NUTS 2021, escala 1:3M. Se ejecuta una vez; el
resultado va versionado.

Es el mapa base del visor: el artifact no puede cargar teselas de ningún
servidor de mapas, así que se dibuja con estos polígonos.

Licencia: © EuroGeographics para los límites administrativos (atribución).

    python herramientas/generar_regiones.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from incendios.red import sesion  # noqa: E402

URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_2021_4326_LEVL_{}.geojson"
NIVELES = {2: "comunidad", 3: "provincia"}
DESTINO = Path(__file__).resolve().parent.parent / "incendios" / "datos" / "regiones_espana.geojson"


def _redondear(coordenadas):
    if isinstance(coordenadas[0], (int, float)):
        return [round(coordenadas[0], 4), round(coordenadas[1], 4)]
    return [_redondear(c) for c in coordenadas]


async def main() -> None:
    features = []
    async with sesion() as s:
        for nivel, tipo in NIVELES.items():
            for f in (await s.get(URL.format(nivel))).json()["features"]:
                p = f["properties"]
                if p["CNTR_CODE"] != "ES" or p["NUTS_ID"].startswith("ESZ"):   # ESZ: "extra-regio"
                    continue
                features.append({"type": "Feature",
                                 "properties": {"tipo": tipo, "id": p["NUTS_ID"], "nombre": p["NAME_LATN"]},
                                 "geometry": {"type": f["geometry"]["type"],
                                              "coordinates": _redondear(f["geometry"]["coordinates"])}})
    DESTINO.write_text(json.dumps({
        "type": "FeatureCollection",
        "fuente": "Eurostat GISCO, NUTS 2021 1:3M (© EuroGeographics), " + URL.format("N"),
        "features": features,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cuenta = {t: sum(f["properties"]["tipo"] == t for f in features) for t in NIVELES.values()}
    print(f"{DESTINO} ({DESTINO.stat().st_size // 1024} KB, {cuenta})")


if __name__ == "__main__":
    asyncio.run(main())
