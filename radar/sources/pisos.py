"""pisos.com.

No expone JSON, pero su parrilla es HTML regular y estable: cada anuncio es un
<div class="ad-preview" id="..."> con el precio limpio en `data-ad-price`.

Filtros utiles en la propia URL (verificados contra el portal):
    /venta/pisos-{provincia}/hasta-{N}-euros/           -> tope de precio
    /venta/pisos-{provincia}/fecharecientedesde-desc/   -> mas recientes primero
    /venta/pisos-{provincia}/.../{pagina}/              -> paginacion
El portal ignora los filtros de habitaciones y banos en la URL, asi que esos
dos se aplican despues, en local.
"""
from __future__ import annotations

import html as htmllib
import re
from typing import Iterator, List, Optional

from .. import occupancy
from ..models import Listing
from .base import Source

BASE = "https://www.pisos.com"

CARD_RE = re.compile(
    r'<div id="(?P<id>[^"]+)" class="ad-preview[^"]*"\s+data-lnk-href="(?P<url>[^"]+)"'
    r'(?P<body>.*?)'
    r'(?=<div id="[^"]+" class="ad-preview|<div class="pagination|</main)', re.S)
PRICE_RE = re.compile(r'data-ad-price="(\d+)"')
PRICE_TXT_RE = re.compile(r'class="ad-preview__price">\s*([^<]+)<')
TITLE_RE = re.compile(r'class="ad-preview__title">([^<]*)<')
SUBTITLE_RE = re.compile(r'class="[^"]*ad-preview__subtitle[^"]*">([^<]*)<')
CHAR_RE = re.compile(r'class="ad-preview__char[^"]*">([^<]*)<')
DESC_RE = re.compile(r'class="ad-preview__description">([^<]*)<')
TOTAL_RE = re.compile(r'([\d.]+)\s*resultados')
MUNI_RE = re.compile(r'\(([^)]+)\)\s*$')

TIPOS = ("atico", "duplex", "piso", "apartamento", "estudio", "casa",
         "chalet", "adosado", "pareado", "loft", "bajo", "finca")


class Pisos(Source):
    name = "pisos"
    label = "pisos.com"

    def scan(self, province: str, filtros: dict, max_pages: int,
             newest_first: bool = True) -> Iterator[Listing]:
        self.completado = False
        slug = self.cfg.get("provincias", {}).get(province)
        if not slug:
            self.log.warning("sin slug de pisos.com para %s", province)
            return

        segments: List[str] = []
        if filtros.get("precio_max"):
            segments.append(f"hasta-{int(filtros['precio_max'])}-euros")
        if newest_first:
            segments.append("fecharecientedesde-desc")
        suffix = "".join(f"{s}/" for s in segments)

        for page in range(1, max_pages + 1):
            url = f"{BASE}/venta/{slug}/{suffix}"
            if page > 1:
                url += f"{page}/"

            doc = self.fetcher.get(url)
            if not doc:
                return
            if page == 1:
                m = TOTAL_RE.search(doc)
                if m:
                    self.log.info("pisos.com %s: %s resultados tras filtros del portal",
                                  province, m.group(1))

            found = 0
            for lst in self._parse_page(doc, province):
                found += 1
                yield lst
            if found == 0:
                self.completado = True
                return

    # ------------------------------------------------------------------ internos

    def _parse_page(self, doc: str, province: str) -> Iterator[Listing]:
        for m in CARD_RE.finditer(doc):
            lst = self._parse_card(m.group("id"), m.group("url"),
                                   m.group("body"), province)
            if lst:
                yield lst

    def _parse_card(self, cid: str, url: str, body: str,
                    province: str) -> Optional[Listing]:
        if not url:
            return None

        title = _txt(TITLE_RE.search(body))
        subtitle = _txt(SUBTITLE_RE.search(body))
        desc = _txt(DESC_RE.search(body))

        pm = PRICE_RE.search(body)
        price = int(pm.group(1)) if pm else self._int(_txt(PRICE_TXT_RE.search(body)))

        rooms, baths, area = self._chars(body)

        # "Atico en calle de la Cruz, 1" -> atico
        low_title = occupancy.normalize(title)
        ptype = next((t for t in TIPOS if low_title.startswith(t)), "")

        # "Punta del Moral (Ayamonte)" -> Ayamonte
        mm = MUNI_RE.search(subtitle)
        muni = mm.group(1).strip() if mm else subtitle.strip()

        occ, reason = occupancy.detect(title, subtitle, desc,
                                       occupancy.from_url(url))

        return Listing(
            source=self.name,
            source_id=cid,
            url=url if url.startswith("http") else BASE + url,
            title=title,
            price=price,
            rooms=rooms,
            baths=baths,
            area=area,
            municipality=muni,
            province=province,
            ptype=ptype,
            occupied=occ,
            occupied_reason=reason,
            description=desc,
        )

    def _chars(self, body: str):
        """Lee la fila de caracteristicas: '3 habs.', '2 banos', '110 m2'."""
        rooms = baths = area = None
        for chunk in CHAR_RE.findall(body):
            chunk = htmllib.unescape(chunk).strip()
            low = occupancy.normalize(chunk)   # sin acentos: 'banos', 'm2'
            if "hab" in low or "dormitor" in low:
                rooms = rooms if rooms is not None else self._int(chunk)
            elif "bano" in low or "aseo" in low:
                baths = baths if baths is not None else self._int(chunk)
            elif "m2" in low or "m²" in low:
                area = area if area is not None else self._int(chunk)
        return rooms, baths, area


def _txt(m) -> str:
    return htmllib.unescape(m.group(1)).strip() if m else ""
