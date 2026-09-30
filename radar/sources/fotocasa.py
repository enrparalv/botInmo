"""Fotocasa.

La mejor fuente de las tres: la pagina de resultados incluye un
<script type="application/json" id="__initial_props__"> con el listado ya
estructurado, incluidos los flags `isOccupied`, `isRentedWithTenants`,
`isAuctioned` y `isBareOwnership`, que son exactamente el criterio de
"que no este ocupado".

Ademas acepta filtros en servidor (maxPrice, minRooms, minBathrooms) y
`sortType=publicationDate`, asi que el barrido rapido solo necesita mirar
las primeras paginas para capturar todo lo publicado desde la ultima vez.
"""
from __future__ import annotations

import json
import re
from typing import Iterator, Optional

from .. import occupancy
from ..models import Listing
from .base import Source

BASE = "https://www.fotocasa.es"
JSON_RE = re.compile(
    r'<script type="application/json" id="__initial_props__">(.*?)</script>', re.S)

# buildingType / buildingSubtype -> etiqueta legible
TIPOS = {
    "Flat": "piso", "Apartment": "apartamento", "Penthouse": "atico",
    "Duplex": "duplex", "Studio": "estudio", "House": "casa",
    "Loft": "loft", "Rural": "casa rural", "GroundFloor": "bajo",
}


class Fotocasa(Source):
    name = "fotocasa"
    label = "Fotocasa"

    def scan(self, province: str, filtros: dict, max_pages: int,
             newest_first: bool = True) -> Iterator[Listing]:
        self.completado = False
        slug = self.cfg.get("provincias", {}).get(province)
        if not slug:
            self.log.warning("sin slug de Fotocasa para %s", province)
            return

        params = []
        if filtros.get("precio_max"):
            params.append(f"maxPrice={int(filtros['precio_max'])}")
        if filtros.get("precio_min"):
            params.append(f"minPrice={int(filtros['precio_min'])}")
        if filtros.get("dormitorios_min"):
            params.append(f"minRooms={int(filtros['dormitorios_min'])}")
        if filtros.get("banos_min"):
            params.append(f"minBathrooms={int(filtros['banos_min'])}")
        if newest_first:
            params.append("sortType=publicationDate")
        query = "&".join(params)

        for page in range(1, max_pages + 1):
            path = f"/es/comprar/viviendas/{slug}/todas-las-zonas/l"
            if page > 1:
                path += f"/{page}"
            url = f"{BASE}{path}?{query}" if query else f"{BASE}{path}"

            html = self.fetcher.get(url)
            if not html:
                return
            data = self._extract(html)
            if data is None:
                self.log.warning("sin JSON en la pagina %s de %s", page, province)
                return

            items = data.get("realEstates") or []
            if not items:
                self.completado = True
                return
            if page == 1:
                self.log.info("Fotocasa %s: %s anuncios tras filtros del portal",
                              province, data.get("count"))

            for raw in items:
                lst = self._parse(raw, province)
                if lst:
                    yield lst

            # Fotocasa pagina de 30 en 30; si trae menos, era la ultima.
            total = data.get("count") or 0
            if page * 30 >= total:
                self.completado = True
                return

    # ------------------------------------------------------------------ internos

    @staticmethod
    def _extract(html: str) -> Optional[dict]:
        m = JSON_RE.search(html)
        if not m:
            return None
        try:
            props = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        return (props.get("initialSearch") or {}).get("result")

    def _parse(self, raw: dict, province: str) -> Optional[Listing]:
        addr = raw.get("address") or {}
        detail = _path(raw.get("detail")) or _path(raw.get("detailWithParams"))
        if detail and not detail.startswith("http"):
            detail = BASE + detail

        feats = {f.get("key"): f.get("value") for f in (raw.get("features") or [])}

        # Los flags estructurados de Fotocasa son la senal mas fiable que existe
        # en los tres portales para saber si el inmueble se entrega libre.
        occ_flag = None
        occ_reason = ""
        for campo, motivo in (("isOccupied", "Fotocasa lo marca como ocupado"),
                              ("isRentedWithTenants", "Fotocasa: alquilado con inquilinos"),
                              ("isAuctioned", "Fotocasa: en subasta"),
                              ("isBareOwnership", "Fotocasa: nuda propiedad")):
            if raw.get(campo):
                occ_flag, occ_reason = True, motivo
                break

        subtype = raw.get("buildingSubtype") or ""
        btype = raw.get("buildingType") or ""
        ptype = TIPOS.get(btype, TIPOS.get(subtype.split("_")[0], btype or subtype)).lower()

        title = (raw.get("promotionTitle")
                 or f"{ptype.capitalize()} en {addr.get('neighborhood') or addr.get('municipality') or ''}".strip())
        desc = raw.get("description") or ""

        occ, reason = occupancy.combine(
            occ_flag, occ_reason,
            occupancy.detect(title, desc, occupancy.from_url(detail)))

        rid = raw.get("id") or raw.get("realEstateAdId")
        if not rid or not detail:
            return None

        date = raw.get("date") or {}
        days = date.get("diff") if date.get("unit") == "DAYS" else None

        return Listing(
            source=self.name,
            source_id=str(rid),
            url=detail,
            title=title.strip(),
            price=self._int(raw.get("rawPrice") or raw.get("price")),
            rooms=self._int(feats.get("rooms")),
            baths=self._int(feats.get("bathrooms")),
            area=self._int(feats.get("surface")),
            municipality=(addr.get("municipality") or addr.get("city") or "").strip(),
            province=(addr.get("province") or province).strip(),
            ptype=ptype,
            occupied=occ,
            occupied_reason=reason,
            description=desc,
            published_days=days,
            agency=(raw.get("clientAlias") or "").strip(),
        )


def _path(value) -> str:
    """Fotocasa devuelve las urls como {"es-ES": "/es/comprar/..."}."""
    if isinstance(value, dict):
        return (value.get("es-ES") or next(iter(value.values()), "") or "").split("?")[0]
    return (value or "").split("?")[0]
