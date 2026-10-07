#!/usr/bin/env python3
"""
Incendios V0.0 — crawling de satélites y viento sobre España.

    python crawl.py                 # todo: satélites + viento
    python crawl.py satelites       # solo focos y áreas quemadas
    python crawl.py viento          # solo viento (AEMET + Puertos + Open-Meteo)
    python crawl.py --horas 48 --dias-effis 14
    python crawl.py --abrir         # y abre el visor en el navegador al terminar

Para pegar las claves y ver cada paso, usar `pipeline_incendios.ipynb`.

Todo el crawling va por crawl4ai (ver `incendios/red.py`). Las fuentes se
lanzan en paralelo y cada una aislada: si una falla o le falta la clave, queda
anotada en `estado_fuentes.json` y el resto sigue. Solo se guarda lo que cae en
España (contorno real, ver `incendios/geo.py`). Salida en `output/<marca UTC>/`:

    focos.geojson              FIRMS (VIIRS/MODIS) + SEVIRI, con viento en el foco
    areas_quemadas.geojson     EFFIS
    incidencias_oficiales.geojson  INFOCA, FIDIAS (CLM), Bombers (Cataluña), INFORCYL (CyL)
    viento_estaciones.geojson  AEMET, última lectura por estación
    viento_puertos.geojson     Puertos del Estado: boyas, mareógrafos y puertos
    viento_rejilla.geojson     Open-Meteo en las 52 capitales de provincia
    estado_fuentes.json        ok / omitida / error, nº de registros y tiempo
    visor.html                 mapa interactivo con todo lo anterior (abrir en el navegador)
"""
from __future__ import annotations

import argparse
import asyncio

from incendios import cobertura, incidencias as incid, riesgo, visor
from incendios.pipeline import a_geojson, anotar, ejecutar, ejecutar_con_detalle, guardar, nueva_salida, resumen
from incendios.satelites import effis, firms, lsasaf
from incendios.viento import aemet, openmeteo, puertos


async def _crawl(args, salida, estado: dict) -> dict:
    satelites, viento = args.que in ("todo", "satelites"), args.que in ("todo", "viento")
    firms_, seviri, areas, oficiales, prevision, estaciones, costa, rejilla = await asyncio.gather(
        ejecutar(estado, "NASA FIRMS", firms.obtener_focos(args.horas)) if satelites else _nada(),
        ejecutar(estado, "EUMETSAT LSA-SAF (SEVIRI)", lsasaf.obtener_focos(args.horas_seviri)) if satelites else _nada(),
        ejecutar(estado, "EFFIS (áreas quemadas)", effis.obtener_areas(args.dias_effis)) if satelites else _nada(),
        ejecutar_con_detalle(estado, "Incidencias 112 (oficiales)", incid.obtener_incidencias(args.dias_incidencias))
        if satelites else _nada(),
        ejecutar(estado, "Riesgo de incendio (AEMET)", riesgo.obtener_prevision()) if satelites else _nada(),
        ejecutar(estado, "AEMET (estaciones)", aemet.obtener_estaciones()) if viento else _nada(),
        ejecutar(estado, "Puertos del Estado (costa)", puertos.obtener_estaciones()) if viento else _nada(),
        ejecutar(estado, "Open-Meteo (capitales)", openmeteo.obtener_rejilla()) if viento else _nada(),
    )

    focos: list = []
    if satelites:
        # "0 focos" de SEVIRI solo significa "no hay fuego" si pudo ver España.
        await anotar(estado, "EUMETSAT LSA-SAF (SEVIRI)", "vigilancia", lsasaf.vigilancia_espana())
        focos = sorted(firms_ + seviri, key=lambda f: f["fecha_utc"], reverse=True)
        await ejecutar(estado, cobertura.NOMBRE_FUENTE, cobertura.anotar_async(focos, oficiales))
        if focos and not args.sin_viento_focos:
            # Capa de emergencia: depende de los focos, así que va después.
            por_celda = dict(await ejecutar(estado, "Open-Meteo (viento en focos)",
                                            openmeteo.viento_en_focos(focos)))
            for f in focos:
                f["viento_local"] = por_celda.get(openmeteo.celda_de(f))
        guardar(salida, "focos.geojson", a_geojson(focos))
        guardar(salida, "areas_quemadas.geojson", a_geojson(areas, geometria=lambda a: a.get("geometria")))
        guardar(salida, "incidencias_oficiales.geojson", a_geojson(oficiales))

    if viento:
        guardar(salida, "viento_estaciones.geojson", a_geojson(estaciones))
        guardar(salida, "viento_puertos.geojson", a_geojson(costa))
        guardar(salida, "viento_rejilla.geojson", a_geojson(rejilla))
    return {"focos": focos, "areas": areas, "estaciones": estaciones, "costa": costa, "rejilla": rejilla,
            "incidencias": oficiales, "riesgo": prevision}


async def _nada() -> list:
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("que", nargs="?", default="todo", choices=("todo", "satelites", "viento"))
    ap.add_argument("--horas", type=int, default=24, help="ventana de focos FIRMS (def. 24)")
    ap.add_argument("--horas-seviri", type=float, default=3, help="ventana de focos SEVIRI (def. 3)")
    ap.add_argument("--dias-effis", type=int, default=7, help="ventana de áreas quemadas (def. 7)")
    ap.add_argument("--dias-incidencias", type=int, default=3, help="incidencias oficiales extinguidas a mostrar (def. 3 días)")
    ap.add_argument("--sin-viento-focos", action="store_true", help="no consultar viento en cada foco")
    ap.add_argument("--abrir", action="store_true", help="abrir el visor en el navegador al terminar")
    args = ap.parse_args()

    salida = nueva_salida()
    estado: dict = {}
    datos = asyncio.run(_crawl(args, salida, estado))
    guardar(salida, "estado_fuentes.json", {"generado_utc": salida.name, "fuentes": estado})
    pagina = visor.generar(salida, **datos, estado=estado, horas_focos=args.horas, dias_effis=args.dias_effis,
                           horas_seviri=args.horas_seviri, dias_incidencias=args.dias_incidencias)
    print(f"\nSalida: {salida}\nVisor:  {pagina}\n\n{resumen(estado)}")
    if args.abrir:
        visor.abrir(pagina)


if __name__ == "__main__":
    main()
