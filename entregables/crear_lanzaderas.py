#!/usr/bin/env python3
"""Genera las dos lanzaderas (EJECUTAR_Reto_Incendios.ipynb y EJECUTAR_Reto_Vientos.ipynb) junto a los zips."""
import json, sys
from pathlib import Path

DESTINO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "listos"

RETOS = {
    "incendios": dict(
        nom="Incendios",
        resumen="focos de calor (NASA FIRMS, SEVIRI), áreas quemadas (EFFIS), incidencias 112 y riesgo de AEMET",
        claves={"AEMET_API_KEY": ("AEMET_API_KEY", "riesgo previsto (AEMET)"), "LSASAF_USUARIO": ("LSASAF_USER", "focos SEVIRI"),
                "LSASAF_PASSWORD": ("LSASAF_PASSWORD", "focos SEVIRI"), "FIRMS_MAP_KEY": ("FIRMS_MAP_KEY", "opcional: FIRMS")},
        params=[("HORAS_FOCOS", 24, "ventana de focos FIRMS (24, 48 o hasta 168 h)", "--horas"),
                ("HORAS_SEVIRI", 3, "ventana de focos SEVIRI", "--horas-seviri"),
                ("DIAS_EFFIS", 7, "áreas quemadas publicadas o revisadas", "--dias-effis"),
                ("DIAS_INCIDENCIAS", 3, "incidencias 112 ya extinguidas que se incluyen", "--dias-incidencias")]),
    "vientos": dict(
        nom="Vientos",
        resumen="viento de AEMET (~855 estaciones), Puertos del Estado (boyas y puertos) y Open-Meteo (capitales)",
        claves={"AEMET_API_KEY": ("AEMET_API_KEY", "las ~855 estaciones de AEMET")}, params=[]),
}

def md(txt): return {"cell_type": "markdown", "metadata": {}, "source": txt.strip("\n").splitlines(keepends=True)}
def code(txt): return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": txt.strip("\n").splitlines(keepends=True)}

def construir(reto: str, c: dict) -> dict:
    claves_txt = "\n".join(f'{k:<16}= ""   # {d}' for k, (_, d) in c["claves"].items())
    params_txt = "\n".join(f"{n:<16}= {v}{' ' * (3 - len(str(v)))}# {d}" for n, v, d, _ in c["params"])
    args_py = "[" + ", ".join(f'"{flag}", str({n})' for n, _, _, flag in c["params"]) + "]"
    mapa_claves = repr({k: v[0] for k, v in c["claves"].items()})
    cfg = f'''RETO = "{reto}"
ZIP = None                   # None = buscarlo solo; o p. ej. "/Users/.../Downloads/reto_{reto}.zip"
DESCOMPRIMIR_EN = None       # None = al lado del zip, en una carpeta reto_{reto}
VOLVER_A_DESCOMPRIMIR = False
PROYECTO = None              # ruta de la carpeta reto_{reto} ya descomprimida, para no usar el zip
INSTALAR_LIBRERIAS = True    # instalar en este kernel las que falten (requirements.txt + pandas)

# Claves: las que dejes vacías se ignoran y se usa lo que ya haya en .env
{claves_txt}

DESCARGAR_DATOS = True       # True = descargar datos nuevos; False = usar la última descarga
{params_txt}
ABRIR = "local"              # "local" abre el mapa en el navegador · "ninguna" solo muestra el botón'''
    claves_md = " ".join(f"`{k}`" for k in c["claves"])
    params_md = "".join(f"- **`{n}`**: {d}.\n" for n, _, d, _ in c["params"])
    celdas = [
        md(f"""# ▶ Ejecutar el Reto {c['nom']} · mapa interactivo

**Lanzadera del reto {c['nom']}.** Pulsa **Run All** (ejecutar todo) y el mapa se abre solo en el navegador.
Descarga {c['resumen']}.

| Paso | Qué hace |
|---|---|
| 1. Configuración | Opciones; por defecto no hace falta tocar nada |
| 2. Descomprimir | Busca `reto_{reto}.zip` a su lado o en Descargas y lo descomprime. Si no hay zip, usa la carpeta ya descomprimida |
| 3. Librerías | Revisa que estén instaladas (versiones de `requirements.txt`) y, si faltan, las instala en este kernel |
| 4. Claves | Guarda en `.env` las claves que pegues en el paso 1 |
| 5. Descargar datos | Opcional: descarga los datos con el reto y los guarda en `output/` |
| 6. Preparar el mapa | Genera `mapa_{reto}.html` con la última descarga si falta o está desactualizado |
| 7. Abrir | Abre ese archivo en el navegador: **el mapa no necesita servidor** (sí internet para el mapa base) |"""),
        md(f"""## 1 · Configuración

- **`ZIP`**: `None` para buscarlo solo (`reto_{reto}*.zip` junto a este notebook, en la carpeta donde arrancó Jupyter o en Descargas); o la ruta de un zip concreto.
- **`DESCOMPRIMIR_EN`**: `None` = al lado del zip, en una carpeta `reto_{reto}`.
- **`VOLVER_A_DESCOMPRIMIR`**: `True` para descomprimir otra vez (sobrescribe los archivos del zip; no borra tu `.env` ni tus datos).
- **`PROYECTO`**: si no quieres usar el zip, la ruta de la carpeta `reto_{reto}` ya descomprimida.
- **`INSTALAR_LIBRERIAS`**: instala en este kernel las librerías que falten.
- **Claves** ({claves_md}): se guardan en `.env`. ⚠️ Si las pegas aquí, no compartas este notebook con ellas.
- **`DESCARGAR_DATOS`**: `True` descarga datos nuevos; `False` usa la última descarga guardada.
{params_md}- **`ABRIR`**: `"local"` abre el mapa; `"ninguna"`, solo muestra el botón."""),
        code(cfg),
        md(f"""## 2 · Descomprimir

Se busca el zip más reciente. Si su carpeta `reto_{reto}` ya está descomprimida, se reutiliza. Si no hay zip, se usa
una carpeta que tenga `reto_{reto}.py` y `incendios/` (la más reciente)."""),
        code(f'''import json, os, re, shutil, subprocess, sys, webbrowser, zipfile
from pathlib import Path
from IPython.display import HTML, Markdown, display

def _carpetas_inicio() -> list:
    """Dónde buscar: la carpeta del notebook (VS Code o Jupyter la indican), la carpeta de trabajo de Jupyter y
    sus superiores, y Descargas. Jupyter no siempre arranca en la carpeta del notebook."""
    rutas = []
    for nb in (globals().get("__vsc_ipynb_file__"), os.environ.get("JPY_SESSION_NAME")):
        if nb and Path(nb).expanduser().exists():
            rutas.append(Path(nb).expanduser().resolve().parent)
    cwd = Path.cwd().resolve()
    rutas += [cwd, *list(cwd.parents)[:3]]
    rutas += [Path.home() / "Downloads", Path.home() / "Descargas"]
    unicas = []
    for r in rutas:
        if r.is_dir() and r not in unicas:
            unicas.append(r)
    return unicas

def _es_proyecto(c: Path) -> bool:
    return (c / f"reto_{{RETO}}.py").exists() and (c / "incendios" / "__init__.py").exists()

def buscar(bases: list):
    """Zips reto_<reto>*.zip y carpetas del reto en cada carpeta de inicio y en sus subcarpetas directas."""
    zips, proyectos = [], []
    for base in bases:
        try:
            hijas = [c for c in base.iterdir() if c.is_dir() and not c.name.startswith(".")]
        except OSError:
            hijas = []
        for c in [base, *hijas]:
            c = c.resolve()
            zips += [z.resolve() for z in c.glob(f"reto_{{RETO}}*.zip") if z.resolve() not in zips]
            if c not in proyectos and _es_proyecto(c):
                proyectos.append(c)
    zips.sort(key=lambda z: z.stat().st_mtime, reverse=True)
    proyectos.sort(key=lambda c: (c / f"reto_{{RETO}}.py").stat().st_mtime, reverse=True)
    return zips, proyectos

def descomprimir(zip_path: Path, destino_padre: Path) -> Path:
    """Descomprime comprobando que ningún archivo se salga de la carpeta de destino."""
    destino_padre = destino_padre.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for nombre in z.namelist():
            final = (destino_padre / nombre).resolve()
            if destino_padre != final and destino_padre not in final.parents:
                raise ValueError(f"El zip tiene una ruta no permitida: {{nombre}}")
        raices = {{n.split("/")[0] for n in z.namelist() if n.strip("/")}}
        z.extractall(destino_padre)
    return destino_padre / sorted(raices)[0] if len(raices) == 1 else destino_padre

BUSCADO_EN = _carpetas_inicio()
zips, proyectos = buscar(BUSCADO_EN)
RAIZ, ORIGEN = None, ""
if PROYECTO:
    p = Path(PROYECTO).expanduser().resolve()
    RAIZ, ORIGEN = (p, "carpeta indicada en PROYECTO") if _es_proyecto(p) else (None, "")
else:
    zip_elegido = Path(ZIP).expanduser().resolve() if ZIP else (zips[0] if zips else None)
    if zip_elegido is not None and zip_elegido.exists():
        padre = Path(DESCOMPRIMIR_EN).expanduser() if DESCOMPRIMIR_EN else zip_elegido.parent
        objetivo = padre.resolve() / f"reto_{{RETO}}"
        if _es_proyecto(objetivo) and not VOLVER_A_DESCOMPRIMIR:
            RAIZ, ORIGEN = objetivo, f"ya estaba descomprimido de `{{zip_elegido.name}}`"
        else:
            padre.mkdir(parents=True, exist_ok=True)
            RAIZ = descomprimir(zip_elegido, padre)
            ORIGEN = f"descomprimido ahora de `{{zip_elegido.name}}`"
    elif proyectos:
        RAIZ, ORIGEN = proyectos[0], "carpeta del reto (no hay zip)"

if RAIZ is None or not _es_proyecto(RAIZ):
    donde = "".join(f"<li><code>{{c}}</code></li>" for c in BUSCADO_EN)
    display(HTML("<div style='font-family:system-ui;padding:12px 14px;border:1px solid #c98a00;border-radius:8px;max-width:760px;line-height:1.5'>"
                 f"<b>No encuentro el reto.</b> He buscado <code>reto_{{RETO}}*.zip</code> y carpetas con <code>reto_{{RETO}}.py</code> "
                 "e <code>incendios/</code> en estas carpetas y en sus subcarpetas:<ul>" + donde + "</ul>"
                 "Pon el zip junto a este notebook, o escribe su ruta en <code>ZIP</code> (paso 1), y vuelve a ejecutar.</div>"))
    RAIZ = None
else:
    display(Markdown(f"""**Reto:** `{{RETO}}`

**Carpeta:** `{{RAIZ}}` ({{ORIGEN}})

**Archivos:** {{", ".join(sorted(p.name for p in RAIZ.iterdir() if p.is_file() and not p.name.startswith(".")))}}"""))'''),
        md("""## 3 · Librerías

Compara las librerías instaladas en **este** kernel con las de `requirements.txt` (más `pandas`). Si falta alguna y
`INSTALAR_LIBRERIAS = True`, la instala con el mismo Python de este notebook. La primera vez puede tardar unos minutos."""),
        code('''import importlib
import importlib.metadata as md

def _revisar_librerias(carpeta: Path):
    pedidas = {"pandas": ""}
    req = carpeta / "requirements.txt"
    if req.exists():
        for linea in req.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\\s*([A-Za-z0-9_.\\-]+)\\s*((?:[=<>!~]=?|===)\\s*[^\\s#;]+)?", linea.split("#")[0])
            if m:
                pedidas[m.group(1)] = (m.group(2) or "").replace(" ", "")
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:          # sin `packaging` solo se comprueba que estén instaladas
        SpecifierSet = Version = None
    filas, faltan, distintas = [], [], []
    for paquete, requisito in pedidas.items():
        try:
            instalada = md.version(paquete)
        except md.PackageNotFoundError:
            filas.append(f"  ✗ {paquete:<10} no instalada" + (f"   (pide {requisito})" if requisito else ""))
            faltan.append(paquete)
            continue
        ok = True
        if requisito and SpecifierSet:
            ok = Version(instalada) in SpecifierSet(requisito if requisito[0] in "<>=!~" else "==" + requisito)
        filas.append(f"  {'✓' if ok else '!'} {paquete:<10} {instalada}" + ("" if ok else f"   (pide {requisito})"))
        if not ok:
            distintas.append(paquete)
    return filas, faltan, distintas

LIBRERIAS_OK = False
if RAIZ is not None:
    print(f"Python {sys.version.split()[0]} · {sys.executable}\\n")
    filas, faltan, distintas = _revisar_librerias(RAIZ)
    print("\\n".join(filas))
    if faltan and INSTALAR_LIBRERIAS:
        cmd = [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "pandas"]
        print("\\nInstalando:", " ".join(cmd), "\\n")
        proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for linea in proc.stdout:
            print(linea, end="")
        proc.wait()
        importlib.invalidate_caches()
        filas, faltan, distintas = _revisar_librerias(RAIZ)
        print("\\nTras instalar:\\n" + "\\n".join(filas))
    LIBRERIAS_OK = not faltan
    if faltan:
        print("\\n✗ Faltan librerías: " + ", ".join(faltan) + ". Pon INSTALAR_LIBRERIAS = True o instálalas a mano y vuelve a ejecutar.")
    elif distintas:
        print("\\nAviso: hay versiones distintas a las de requirements.txt (" + ", ".join(distintas) + "). Puede funcionar, pero no está probado.")
    else:
        print("\\nTodo en orden ✓")
else:
    print("Nada que revisar: no se ha encontrado el reto (paso 2).")'''),
        md(f"""## 4 · Claves

Escribe en el `.env` de la carpeta del reto las claves que hayas pegado en el paso 1 (si no hay `.env`, parte de `.env.example`).
Las vacías se ignoran y se conserva lo que ya hubiera. Nunca se imprime una clave entera: solo inicio, final y longitud."""),
        code(f'''ENV = {mapa_claves}   # variable del notebook -> variable de .env
if RAIZ is not None:
    ruta_env = RAIZ / ".env"
    if not ruta_env.exists() and (RAIZ / ".env.example").exists():
        shutil.copy(RAIZ / ".env.example", ruta_env)
    lineas = ruta_env.read_text(encoding="utf-8").splitlines() if ruta_env.exists() else []
    valores = {{}}
    for l in lineas:
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.split("=", 1)
            valores[k.strip()] = v.strip().strip('"').strip("'")
    pegadas = {{ENV[n]: globals()[n].strip() for n in ENV if globals().get(n, "").strip()}}
    if pegadas:
        nuevas, hechas = [], set()
        for l in lineas:
            k = l.split("=", 1)[0].strip() if "=" in l and not l.lstrip().startswith("#") else None
            if k in pegadas:
                nuevas.append(f"{{k}}={{pegadas[k]}}"); hechas.add(k)
            else:
                nuevas.append(l)
        nuevas += [f"{{k}}={{v}}" for k, v in pegadas.items() if k not in hechas]
        ruta_env.write_text("\\n".join(nuevas) + "\\n", encoding="utf-8")
        valores.update(pegadas)
        print("Guardadas en", ruta_env, "→ ya puedes vaciar las comillas del paso 1.\\n")
    def _oculta(v):
        return "— (vacía)" if not v else (v[:4] + "…" + v[-4:] + f" ({{len(v)}} caracteres)") if len(v) > 12 else "****"
    for variable in ENV.values():
        print(f"{{variable:<16}} {{_oculta(valores.get(variable, ''))}}")
else:
    print("Nada que guardar: no se ha encontrado el reto (paso 2).")'''),
        md(f"""## 5 · Descargar datos (opcional)

Ejecuta `reto_{reto}.py` con el mismo Python de este notebook: descarga las fuentes en paralelo (cada una aislada: si una falla o
le falta la clave, queda anotada y el resto sigue), guarda los ficheros en `output/{reto}/<fecha>/` y genera el mapa.
Con `DESCARGAR_DATOS = False` se omite y se usa la última descarga."""),
        code(f'''DATOS_DESCARGADOS = False
if RAIZ is not None and DESCARGAR_DATOS and LIBRERIAS_OK:
    cmd = [sys.executable, "-u", f"reto_{{RETO}}.py", *{args_py}]
    print("Ejecutando:", " ".join(cmd), "\\n")
    proc = subprocess.Popen(cmd, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={{**os.environ, "PYTHONUNBUFFERED": "1"}})
    for linea in proc.stdout:
        print(linea, end="")
    proc.wait()
    DATOS_DESCARGADOS = proc.returncode == 0
    print("\\nDescarga terminada (mira abajo, en el paso 6, el estado de cada fuente)." if DATOS_DESCARGADOS else "\\n✗ El reto terminó con un error (ver arriba).")
elif RAIZ is not None and DESCARGAR_DATOS:
    print("No se descargan datos: faltan librerías (paso 3).")
else:
    print("No se descargan datos nuevos (DESCARGAR_DATOS = False). Se usa la última descarga.")'''),
        md(f"""## 6 · Preparar el mapa

El mapa es **un único archivo**, `mapa_{reto}.html`, con los datos dentro. Se vuelve a generar solo si falta o si `reto_{reto}.py` es más nuevo que él. Se usa la descarga más reciente de `output/{reto}/`."""),
        code(f'''MAPA = None
CARPETA_DATOS = None
if RAIZ is not None and LIBRERIAS_OK:
    descargas = sorted(m.parent for m in RAIZ.rglob("manifiesto.json") if m.parent.parent.name == RETO)
    CARPETA_DATOS = descargas[-1] if descargas else None
    if CARPETA_DATOS is None:
        print("Todavía no hay datos descargados: pon DESCARGAR_DATOS = True en el paso 1 y vuelve a ejecutar.")
    else:
        MAPA = CARPETA_DATOS / f"mapa_{{RETO}}.html"
        motivo = ("no existe" if not MAPA.exists()
                  else "el código es más nuevo" if MAPA.stat().st_mtime < (RAIZ / f"reto_{{RETO}}.py").stat().st_mtime - 1 else "")
        if motivo:
            print(f"Generando el mapa ({{motivo}})…")
            r = subprocess.run([sys.executable, "-c", f"import reto_{{RETO}} as r; from pathlib import Path; print(r.mapa(Path(r'{{CARPETA_DATOS}}')))"],
                               cwd=RAIZ, capture_output=True, text=True)
            print(r.stdout or r.stderr)
        if MAPA.exists():
            print(f"Mapa listo: {{MAPA}} ({{MAPA.stat().st_size / 1024:.0f}} KB)")
            try:
                estado = json.loads((CARPETA_DATOS / "estado.json").read_text(encoding="utf-8"))
                print("\\nEstado de las fuentes:")
                estados = []
                for fuente, e in estado.items():
                    e = e if isinstance(e, dict) else {{}}
                    estados.append(str(e.get('estado', '?')))
                    print(f"  {{estados[-1]:<8}} {{fuente:<38}} {{e.get('registros', '')}}")
                if estados and "ok" not in estados:
                    print("\\n⚠ Ninguna fuente ha respondido: el mapa saldrá vacío. Revisa tu conexión a internet y vuelve a ejecutar.")
            except (OSError, ValueError):
                pass
        else:
            print("No se ha podido generar el mapa: revisa el mensaje de arriba.")
            MAPA = None
else:
    print("Nada que preparar: falta el reto o las librerías (pasos 2 y 3).")'''),
        md(f"""## 7 · Abrir el mapa

Abre `mapa_{reto}.html` en el navegador directamente desde el archivo: no necesita servidor (sí internet para el mapa base y las
librerías del mapa). Si el navegador no se abre solo, abre el archivo de la ruta que sale abajo con doble clic."""),
        code(f'''if MAPA is not None:
    url_local = MAPA.as_uri()
    abierto = False
    if ABRIR == "local":
        try:
            abierto = webbrowser.open(url_local)
        except Exception:
            abierto = False
    display(HTML(f"""<div style="font-family:system-ui;padding:8px 0;line-height:1.5">
      <a href="{{url_local}}" target="_blank" rel="noopener" style="display:inline-block;background:#c2410c;color:#fff;
         text-decoration:none;padding:14px 28px;border-radius:10px;font-size:17px;font-weight:700">
         &#9654;&nbsp; Abrir el mapa de {c['nom'].lower()}</a>
      <p style="margin:10px 0 0">{{"Se ha abierto en el navegador. " if abierto else ""}}Archivo: <code>{{MAPA}}</code><br>
      <span style="color:#5f6b7a">Si el botón no responde (algunos navegadores no dejan abrir archivos desde un notebook), abre esa ruta
      con doble clic. Para ver los datos paso a paso, abre <code>reto_{reto}.ipynb</code> en la carpeta del reto.</span></p></div>"""))'''),
    ]
    return {"cells": celdas, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 4}

DESTINO.mkdir(parents=True, exist_ok=True)
for reto, c in RETOS.items():
    p = DESTINO / f"EJECUTAR_Reto_{c['nom']}.ipynb"
    p.write_text(json.dumps(construir(reto, c), ensure_ascii=False, indent=1), encoding="utf-8")
    print(p)
