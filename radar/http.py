"""Cliente HTTP educado: cabeceras de navegador, ritmo lento y reintentos.

El objetivo es leer paginas publicas sin castigar al servidor. De ahi la pausa
entre peticiones y el respeto a Retry-After / 429.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional

import requests

log = logging.getLogger("radar.http")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class Fetcher:
    def __init__(self, delay: float = 2.0, retries: int = 3, timeout: int = 30):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        })

    def _throttle(self) -> None:
        """Espera lo que falte para respetar el ritmo, con algo de jitter."""
        wait = self.delay + random.uniform(0, self.delay * 0.4)
        elapsed = time.time() - self._last
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last = time.time()

    def get(self, url: str) -> Optional[str]:
        """Devuelve el HTML, o None si la pagina no se pudo leer."""
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                r = self.s.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("error de red (%s/%s) %s: %s", attempt, self.retries, url, e)
                time.sleep(2 ** attempt)
                continue

            if r.status_code == 200:
                r.encoding = r.encoding or "utf-8"
                return r.text
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429):
                retry_after = int(r.headers.get("Retry-After", 0) or 0)
                pause = retry_after or min(60, 5 * 2 ** attempt)
                log.warning("HTTP %s en %s; esperando %ss", r.status_code, url, pause)
                time.sleep(pause)
                continue
            log.warning("HTTP %s en %s", r.status_code, url)
            time.sleep(2 ** attempt)
        log.error("no se pudo leer tras %s intentos: %s", self.retries, url)
        return None
