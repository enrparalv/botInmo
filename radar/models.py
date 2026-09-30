"""Modelo normalizado de anuncio, comun a todas las fuentes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Listing:
    """Un anuncio normalizado, independientemente del portal de origen."""

    source: str                      # "fotocasa" | "pisos" | "habitaclia"
    source_id: str                   # id dentro del portal
    url: str
    title: str = ""
    price: Optional[int] = None      # euros, entero
    rooms: Optional[int] = None      # dormitorios
    baths: Optional[int] = None      # banos
    area: Optional[int] = None       # m2 construidos
    municipality: str = ""
    province: str = ""
    ptype: str = ""                  # piso, atico, duplex, casa, chalet...
    occupied: Optional[bool] = None  # True ocupado, False libre, None desconocido
    occupied_reason: str = ""        # que lo delato
    description: str = ""
    published_days: Optional[int] = None
    agency: str = ""

    @property
    def key(self) -> str:
        """Clave primaria estable: portal + id del portal."""
        return f"{self.source}:{self.source_id}"

    @property
    def fingerprint(self) -> str:
        """Huella aproximada para detectar el mismo inmueble en varios portales.

        Deliberadamente tosca: municipio + habitaciones + banos + m2 redondeados
        + precio redondeado a la decena de millar. Agrupa duplicados evidentes
        sin arriesgarse a fusionar inmuebles distintos.
        """
        area_bucket = round(self.area / 10) if self.area else 0
        price_bucket = round(self.price / 10000) if self.price else 0
        raw = "|".join(
            str(x)
            for x in (
                _slug(self.municipality),
                self.rooms or 0,
                self.baths or 0,
                area_bucket,
                price_bucket,
            )
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Change:
    """Un hecho detectado que merece notificacion."""

    kind: str                # "nuevo" | "precio" | "retirado"
    listing: Listing
    old_price: Optional[int] = None
    new_price: Optional[int] = None

    @property
    def delta(self) -> Optional[int]:
        if self.old_price is None or self.new_price is None:
            return None
        return self.new_price - self.old_price

    @property
    def delta_pct(self) -> Optional[float]:
        if not self.old_price or self.delta is None:
            return None
        return self.delta / self.old_price * 100.0


def _slug(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
