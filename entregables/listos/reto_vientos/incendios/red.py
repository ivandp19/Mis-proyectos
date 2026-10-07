"""
Capa de red: TODO el crawling pasa por crawl4ai.

Las fuentes de este proyecto son APIs (CSV, JSON, HDF5) y listados de
directorios, no páginas que haya que renderizar, así que se usa la estrategia
HTTP de crawl4ai (`AsyncHTTPCrawlerStrategy`): mismo `AsyncWebCrawler.arun()`,
sin lanzar navegador.

Cómo se comporta esa estrategia, y por qué el código es como es:

* Las cabeceras, el método y el cuerpo van en la estrategia, no en cada
  `arun()`. Por eso cada fuente abre su propia `sesion(...)`: LSA-SAF pide
  autenticación y Puertos del Estado un POST con cuerpo JSON.
* Todo lo que no es `text/html` lo guarda en disco (`downloaded_files`). Se
  apunta a un directorio temporal por sesión, se lee y se borra. Para binarios
  (HDF5 de SEVIRI) es la única forma de obtener los bytes intactos.
* Un HTTP ≠ 2xx no llega como `status_code`: llega como texto en
  `error_message` ("HTTP 401: Unexpected status code…"), y de ahí se saca.
* Por defecto manda `Accept: text/html`, y la API de EFFIS responde entonces
  con su página navegable en vez de JSON. Se fuerza un `Accept` de datos.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig, HTTPCrawlerConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy

from . import config as cfg


class FuenteNoDisponible(RuntimeError):
    """La fuente respondió, pero no con datos utilizables (401, 404, formato…)."""


class FuenteOmitida(RuntimeError):
    """Falta configuración (credenciales) para esta fuente: no es un fallo."""


_STATUS = re.compile(r"HTTP (\d{3})")
_NO_REINTENTAR = {401, 403, 404}


def _ocultar(texto: str) -> str:
    """Quita claves de los mensajes de error (la MAP_KEY de FIRMS va en la ruta)."""
    for secreto in (cfg.FIRMS_MAP_KEY, cfg.AEMET_API_KEY, cfg.LSASAF_PASSWORD):
        if secreto:
            texto = texto.replace(secreto, "***")
    return texto


class Respuesta:
    def __init__(self, texto: str, contenido: bytes | None):
        self.texto = texto
        # Si crawl4ai lo guardó como fichero tenemos los bytes exactos; si era
        # HTML, solo el texto ya decodificado.
        self.contenido = contenido if contenido is not None else texto.encode("utf-8")

    def json(self):
        # AEMET sirve sus `datos` en ISO-8859-15 sin declararlo siempre: se
        # decodifican los bytes, no el texto que adivinó crawl4ai.
        try:
            return json.loads(self.contenido.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(self.contenido.decode("iso-8859-15"))


class Sesion:
    def __init__(self, crawler: AsyncWebCrawler, descargas: Path, timeout_s: float = cfg.TIMEOUT_S):
        self._crawler = crawler
        self._descargas = descargas
        self._config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, verbose=False,
                                        page_timeout=int(timeout_s * 1000))

    async def get(self, url: str, *, params: dict | None = None,
                  reintentos: int = cfg.REINTENTOS) -> Respuesta:
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
        legible = _ocultar(url.split("?")[0])
        error = ""
        for intento in range(1, reintentos + 1):
            r = await self._crawler.arun(url, config=self._config)
            if r.success:
                contenido = None
                for fichero in r.downloaded_files or []:
                    contenido = Path(fichero).read_bytes()
                    Path(fichero).unlink(missing_ok=True)
                return Respuesta(r.html or "", contenido)
            m = _STATUS.search(r.error_message or "")
            error = f"HTTP {m.group(1)}" if m else (r.error_message or "error desconocido").splitlines()[0]
            if m and int(m.group(1)) in _NO_REINTENTAR:
                break
            if intento < reintentos:
                await asyncio.sleep(2 ** intento)
        raise FuenteNoDisponible(_ocultar(f"{error} en {legible}"))


@asynccontextmanager
async def sesion(headers: dict | None = None, *, metodo: str = "GET", cuerpo_json=None,
                 timeout_s: float = cfg.TIMEOUT_S):
    """
    Un `AsyncWebCrawler` HTTP con sus cabeceras y su carpeta de descargas.
    Con `metodo="POST"`, todas las peticiones de la sesión llevan `cuerpo_json`.
    `timeout_s` sube el límite por petición para descargas grandes (teselas de 100 MB).
    """
    descargas = Path(tempfile.mkdtemp(prefix="incendios-"))
    estrategia = AsyncHTTPCrawlerStrategy(browser_config=HTTPCrawlerConfig(
        method=metodo,
        json=cuerpo_json,
        headers={"User-Agent": cfg.USER_AGENT,
                 "Accept": "application/json, text/csv, */*;q=0.8",
                 **(headers or {})},
        downloads_path=str(descargas),
    ))
    try:
        async with AsyncWebCrawler(crawler_strategy=estrategia, verbose=False) as crawler:
            yield Sesion(crawler, descargas, timeout_s)
    finally:
        shutil.rmtree(descargas, ignore_errors=True)
