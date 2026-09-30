"""Habitaclia.

Cada anuncio es un <article class="js-list-item"> con atributos data-* muy
utiles: data-propertysubtype (FLAT, HOUSE...), data-transaction (SALE) y
data-esparticular (PROFESSIONAL / PRIVATE).

Limitacion conocida y deliberada: Habitaclia no ofrece una pagina provincial
rastreable (la provincial va por /vistamapa.htm, que su robots.txt prohibe),
asi que se recorre por municipios, definidos en config.json. La cobertura de
esta fuente es exactamente la de los municipios que se listen ahi.
"""
from __future__ import annotations

import html as htmllib
import re
from typing import Iterator, Optional

from .. import occupancy
from ..models import Listing
from .base import Source

BASE = "https://www.habitaclia.com"

# Cada tarjeta es un <article class="js-list-item"> que CONTIENE otro <article>
# (el bloque de precio) y varios </section> internos, asi que no vale cerrarla
# por etiqueta: se trocea el documento entre inicios de tarjeta consecutivos.
ITEM_START_RE = re.compile(r'<article class="js-list-item[^"]*"(?P<attrs>[^>]*)>')
ATTR_RE = re.compile(r'data-([a-z]+)="([^"]*)"')
HREF_RE = re.compile(r'data-href="([^"]+)"')
PRICE_RE = re.compile(r'itemprop="price"[^>]*>\s*([^<]+)<')
TITLE_RE = re.compile(r'class="list-item-title"[^>]*>\s*<a[^>]*title="([^"]*)"')
FEATURE_RE = re.compile(r'class="list-item-feature"[^>]*>(.*?)</p>', re.S)
LOCATION_RE = re.compile(r'class="list-item-location"[^>]*>\s*<span>([^<]+)')
DESC_RE = re.compile(r'class="[^"]*list-item-description[^"]*"[^>]*>\s*([^<]+)', re.S)
TAG_RE = re.compile(r'<[^>]+>')

SUBTYPES = {
    "FLAT": "piso", "APARTMENT": "apartamento", "PENTHOUSE": "atico",
    "DUPLEX": "duplex", "STUDIO": "estudio", "HOUSE": "casa",
    "CHALET": "chalet", "TERRACED_HOUSE": "adosado", "LOFT": "loft",
    "COUNTRY_HOUSE": "casa rural", "GROUND_FLOOR": "bajo",
}


class Habitaclia(Source):
    name = "habitaclia"
    label = "Habitaclia"

    # Su robots.txt prohibe el parametro `ordenar=`, asi que no hay manera
    # legitima de pedir los anuncios mas recientes primero. Un barrido rapido
    # sobre las primeras paginas se perderia lo nuevo, de modo que esta fuente
    # solo entra en el barrido completo.
    ordena_por_fecha = False

    def scan(self, province: str, filtros: dict, max_pages: int,
             newest_first: bool = True) -> Iterator[Listing]:
        self.completado = False
        municipios = (self.cfg.get("municipios") or {}).get(province) or []
        if not municipios:
            self.log.warning("sin municipios de Habitaclia configurados para %s", province)
            return

        # Esta fuente tiene su propio tope de paginas POR MUNICIPIO, en vez de
        # repartir el presupuesto global. Con 20 municipios por provincia, dejar
        # que cada uno consuma su parte de `paginas_completo` disparaba el
        # barrido a mas de media hora, y Habitaclia es la fuente que mas se
        # solapa con Fotocasa: no compensa gastar ahi el grueso del tiempo.
        per_town = int(self.cfg.get("paginas_por_municipio", 4))

        agotados = True
        for muni in municipios:
            for page in range(1, per_town + 1):
                url = (f"{BASE}/viviendas-{muni}.htm" if page == 1
                       else f"{BASE}/viviendas-{muni}-{page}.htm")
                doc = self.fetcher.get(url)
                if not doc:
                    agotados = False
                    break
                found = 0
                for lst in self._parse_page(doc, province, muni):
                    found += 1
                    yield lst
                if found == 0:
                    break   # este municipio se acabo: bien
            else:
                # El bucle llego al tope de paginas sin quedarse sin anuncios,
                # asi que este municipio tiene mas de los que hemos visto.
                agotados = False

        # Solo cuenta como completo si TODOS los municipios se agotaron. Con el
        # tope por defecto casi nunca ocurre, y es justo lo que queremos: si no
        # hemos visto el catalogo entero, no podemos dar por retirado nada. Sin
        # esto, bajar el tope de paginas marcaba de baja decenas de anuncios que
        # seguian publicados, solo que en paginas que ya no visitamos.
        self.completado = agotados

    # ------------------------------------------------------------------ internos

    def _parse_page(self, doc: str, province: str, muni: str) -> Iterator[Listing]:
        starts = list(ITEM_START_RE.finditer(doc))
        for i, m in enumerate(starts):
            fin = starts[i + 1].start() if i + 1 < len(starts) else len(doc)
            body = doc[m.end():fin]
            lst = self._parse_item(m.group("attrs"), body, province, muni)
            if lst:
                yield lst

    def _parse_item(self, attrs: str, body: str, province: str,
                    muni: str) -> Optional[Listing]:
        a = dict(ATTR_RE.findall(attrs))
        if a.get("transaction") and a["transaction"] != "SALE":
            return None

        hm = HREF_RE.search(attrs) or HREF_RE.search(body)
        if not hm:
            return None
        url = htmllib.unescape(hm.group(1)).split("?")[0]

        rid = a.get("id") or a.get("realestateadid")
        if not rid:
            return None

        title = _txt(TITLE_RE.search(body))
        desc = _txt(DESC_RE.search(body))
        price = self._int(_txt(PRICE_RE.search(body)))
        rooms, baths, area = self._details(body)

        # "Huelva - Centro" -> municipio Huelva, mas fiable que el slug de la url
        loc = _txt(LOCATION_RE.search(body))
        municipality = loc.split("-")[0].strip() if loc else muni.replace("_", " ").title()

        occ, reason = occupancy.detect(title, desc, occupancy.from_url(url))

        return Listing(
            source=self.name,
            source_id=str(rid),
            url=url,
            title=title,
            price=price,
            rooms=rooms,
            baths=baths,
            area=area,
            municipality=municipality,
            province=province,
            ptype=SUBTYPES.get(a.get("propertysubtype", ""), ""),
            occupied=occ,
            occupied_reason=reason,
            description=desc,
        )

    def _details(self, body: str):
        """Lee la linea de caracteristicas.

        Viene toda junta en un solo parrafo, con <sup> intercalados:
            94m<sup>2</sup> - 3 habitaciones - 2 banos - 2.286 EUR/m<sup>2</sup>
        Se parte por " - " y se descarta el precio por metro, que tambien
        contiene "m2" y si no lo filtramos se cuela como superficie.
        """
        m = FEATURE_RE.search(body)
        if not m:
            return None, None, None

        linea = htmllib.unescape(TAG_RE.sub("", m.group(1)))
        rooms = baths = area = None
        for token in linea.split("-"):
            token = token.strip()
            if not token or "€" in token or "/" in token:
                continue
            low = occupancy.normalize(token)
            if "habitacion" in low or "dormitor" in low or low.endswith("hab"):
                rooms = rooms if rooms is not None else self._int(token)
            elif "bano" in low or "aseo" in low:
                baths = baths if baths is not None else self._int(token)
            elif "m2" in low.replace(" ", ""):
                area = area if area is not None else self._int(token)
        return rooms, baths, area


def _txt(m) -> str:
    return htmllib.unescape(m.group(1)).strip() if m else ""
