"""Contrato comun a todas las fuentes."""
from __future__ import annotations

import logging
from typing import Iterator, List

from ..http import Fetcher
from ..models import Listing


class Source:
    name = "base"
    label = "Base"

    #: Si el portal permite ordenar por fecha de publicacion. Los que no pueden
    #: solo son utiles en el barrido completo: en uno rapido no hay forma de
    #: saber en que pagina ha caido un anuncio recien publicado.
    ordena_por_fecha = True

    def __init__(self, cfg: dict, fetcher: Fetcher):
        self.cfg = cfg
        self.fetcher = fetcher
        self.log = logging.getLogger(f"radar.{self.name}")
        #: True solo si el ultimo scan() recorrio el listado hasta agotarlo.
        #: Si se corto por el tope de paginas o por un error de red, queda en
        #: False y NO se pueden dar por retirados los anuncios que no salieron:
        #: simplemente no llegamos a mirar donde estaban.
        self.completado = False

    def scan(self, province: str, filtros: dict, max_pages: int,
             newest_first: bool = True) -> Iterator[Listing]:
        """Recorre las paginas de una provincia y va emitiendo anuncios."""
        raise NotImplementedError

    # ------------------------------------------------------------------ utilidades

    @staticmethod
    def _int(text) -> int | None:
        """Extrae el primer numero de un texto tipo '425.000 EUR' o '3 habs.'."""
        import re
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return int(text)
        m = re.search(r"\d[\d.\s]*", str(text).replace(",", "."))
        if not m:
            return None
        digits = re.sub(r"[^\d]", "", m.group(0))
        return int(digits) if digits else None
