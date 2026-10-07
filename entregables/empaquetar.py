#!/usr/bin/env python3
"""
EMPAQUETAR LOS RETOS PARA PASARLOS POR SEPARADO

Crea dos carpetas independientes (y su .zip), cada una con TODO lo que necesita para ejecutarse sin
el resto del proyecto:

    <destino>/reto_incendios/   reto_incendios.py · reto_incendios.ipynb · incendios/ · LEEME.md
    <destino>/reto_vientos/     reto_vientos.py   · reto_vientos.ipynb   · incendios/ · LEEME.md

El paquete `incendios/` (el código que descarga cada fuente) se copia de tu proyecto Incendios-V0.0.
No se copian `.env` (claves), `__pycache__` ni `.DS_Store`: las claves se escriben en el notebook o en
el `.env` de quien reciba la carpeta.

Ejecútalo UNA vez, desde cualquier sitio:

    python empaquetar.py                              # busca Incendios-V0.0 solo
    python empaquetar.py /ruta/a/Incendios-V0.0       # o se lo indicas
    python empaquetar.py /ruta/a/Incendios-V0.0 --destino ~/Desktop/entrega
    python empaquetar.py /ruta/a/Incendios-V0.0 --extra datos --extra herramientas   # carpetas hermanas que `incendios/` necesite

Al final comprueba que cada carpeta importa bien por sí sola.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RETOS = ("incendios", "vientos")
# `plantillas/` y `visor.py` son del visor antiguo (los retos no lo usan) y llevan un .js: Gmail bloquea
# los zips que contienen .js, .exe, etc. Tampoco se copian los datos que solo usa el visor (relieve, regiones).
COMUN = ("__pycache__", "*.pyc", ".DS_Store", ".env", ".ipynb_checkpoints", ".git",
         "plantillas", "visor.py", "relieve*", "regiones_espana*")
# El reto de vientos no usa la cobertura del suelo (ESA WorldCover): no hace falta arrastrar esos .tif.
IGNORAR = {"incendios": shutil.ignore_patterns(*COMUN), "vientos": shutil.ignore_patterns(*COMUN, "cobertura_*")}
# Dependencias que solo necesita el reto de incendios (SEVIRI, cobertura, INFORCYL).
SOLO_INCENDIOS = ("h5py", "rasterio", "pyproj")


def localizar() -> Path | None:
    cands = []
    for base in (AQUI, Path.cwd()):
        for p in (base, *base.parents):
            cands += [p, *sorted(p.glob("Incendios*")), *sorted(p.glob("*/Incendios*"))]
    cands += sorted(Path.home().glob("Downloads/*/*/Incendios*")) + sorted(Path.home().glob("*/Incendios*"))
    return next((c for c in cands if (c / "incendios" / "__init__.py").exists()), None)


def tamano(ruta: Path) -> float:
    return sum(f.stat().st_size for f in ruta.rglob("*") if f.is_file()) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proyecto", nargs="?", help="carpeta Incendios-V0.0 (la que contiene incendios/)")
    ap.add_argument("--destino", default=str(AQUI / "paquetes"), help="dónde crear las carpetas (def. ./paquetes)")
    ap.add_argument("--extra", action="append", default=[], help="carpeta del proyecto a copiar también (repetible)")
    a = ap.parse_args()

    proyecto = Path(a.proyecto).expanduser().resolve() if a.proyecto else localizar()
    if not proyecto or not (proyecto / "incendios" / "__init__.py").exists():
        sys.exit("No encuentro Incendios-V0.0 (la carpeta que contiene incendios/). Pásala como argumento.")
    destino = Path(a.destino).expanduser().resolve()
    print(f"Proyecto: {proyecto}\nDestino:  {destino}\n")

    fallos = 0
    for reto in RETOS:
        carpeta = destino / f"reto_{reto}"
        if carpeta.exists():
            shutil.rmtree(carpeta)
        carpeta.mkdir(parents=True)
        for nombre in (f"reto_{reto}.py", f"reto_{reto}.ipynb", "LEEME.md"):
            origen = AQUI / f"reto_{reto}" / nombre
            if origen.exists():
                shutil.copy(origen, carpeta / nombre)
        shutil.copytree(proyecto / "incendios", carpeta / "incendios", ignore=IGNORAR[reto])
        for extra in a.extra:
            if (proyecto / extra).is_dir():
                shutil.copytree(proyecto / extra, carpeta / extra, ignore=IGNORAR[reto])
            else:
                print(f"  aviso: no existe {proyecto / extra}")
        req = proyecto / "requirements.txt"
        if req.exists():  # mismas versiones que tu proyecto, sin lo que este reto no usa
            lineas = [l for l in req.read_text(encoding="utf-8").splitlines()
                      if reto == "incendios" or not l.strip().lower().startswith(SOLO_INCENDIOS)]
            (carpeta / "requirements.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
        if (proyecto / ".env.example").exists():
            shutil.copy(proyecto / ".env.example", carpeta / ".env.example")
        (carpeta / "LEEME.md").write_text((carpeta / "LEEME.md").read_text(encoding="utf-8") + f"""
## Esta carpeta es independiente
Lleva dentro todo lo necesario (`incendios/`): no depende de ningún otro proyecto. Requisitos:
`pip install -r requirements.txt pandas`. Las claves (AEMET, LSA-SAF) se escriben en
la primera celda del notebook o en un `.env` dentro de esta carpeta.
""", encoding="utf-8")
        # Prueba de aislamiento: importar el reto desde su carpeta, con el entorno limpio de rutas del proyecto.
        r = subprocess.run([sys.executable, "-B", "-I", "-c", f"import sys; sys.path.insert(0, '.'); import reto_{reto}; print(reto_{reto}.RAIZ)"],
                           cwd=carpeta, capture_output=True, text=True)
        ok = r.returncode == 0 and Path(r.stdout.strip()).resolve() == carpeta.resolve()
        fallos += not ok
        print(f"reto_{reto}: {tamano(carpeta):.1f} MB · {'✓ independiente' if ok else '✗ ' + (r.stderr.strip().splitlines() or ['usa rutas del proyecto'])[-1]}")
        shutil.make_archive(str(destino / f"reto_{reto}"), "zip", destino, f"reto_{reto}")
    print(f"\nZips en {destino}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
