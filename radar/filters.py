"""Aplicacion de los criterios de busqueda sobre los anuncios normalizados.

Los portales filtran parte en servidor, pero no todo (pisos.com ignora
habitaciones y banos en la URL) y ninguno filtra por ocupacion de forma fiable.
Este modulo es la ultima palabra: lo que no pase por aqui no se notifica.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .models import Listing
from .occupancy import normalize

# Tipos que cuentan como "vivienda". Se excluyen garajes, locales, terrenos,
# trasteros y naves, que a veces se cuelan en los listados generales.
TIPOS_VIVIENDA = {
    "piso", "apartamento", "atico", "duplex", "estudio", "loft", "bajo",
    "casa", "chalet", "adosado", "pareado", "casa rural", "finca",
}
TIPOS_PISO_ESTRICTO = {"piso", "apartamento", "atico", "duplex", "bajo", "loft"}

TIPOS_EXCLUIDOS = {
    "garaje", "parking", "local", "oficina", "terreno", "solar",
    "trastero", "nave", "industrial", "negocio",
}


class Filtro:
    def __init__(self, cfg: dict):
        self.provincias = {normalize(p) for p in cfg.get("provincias") or []}
        self.precio_max = cfg.get("precio_max")
        self.precio_min = cfg.get("precio_min") or 0
        self.dormitorios_min = cfg.get("dormitorios_min") or 0
        self.banos_min = cfg.get("banos_min") or 0
        self.excluir_ocupados = bool(cfg.get("excluir_ocupados", True))
        self.incluir_desconocidos = bool(cfg.get("incluir_ocupacion_desconocida", True))
        tipos = cfg.get("tipos", "cualquiera")
        self.tipos: Optional[set]
        if tipos in ("cualquiera", "any", None, ""):
            self.tipos = None
        elif tipos in ("piso", "estricto"):
            self.tipos = TIPOS_PISO_ESTRICTO
        else:
            self.tipos = {normalize(t) for t in tipos}

    def check(self, l: Listing) -> Tuple[bool, str]:
        """Devuelve (pasa, motivo_del_descarte)."""
        if self.provincias and normalize(l.province) not in self.provincias:
            return False, f"provincia {l.province!r} fuera del ambito"

        tipo = normalize(l.ptype)
        if tipo in TIPOS_EXCLUIDOS:
            return False, f"no es vivienda ({l.ptype})"
        if self.tipos is not None and tipo and tipo not in self.tipos:
            return False, f"tipo {l.ptype!r} no buscado"

        if l.price is None:
            return False, "sin precio publicado"
        if self.precio_max and l.price > self.precio_max:
            return False, f"precio {l.price} > {self.precio_max}"
        if l.price < self.precio_min:
            return False, f"precio {l.price} < {self.precio_min}"

        if self.dormitorios_min:
            if l.rooms is None:
                return False, "no indica dormitorios"
            if l.rooms < self.dormitorios_min:
                return False, f"{l.rooms} dormitorios < {self.dormitorios_min}"

        if self.banos_min:
            if l.baths is None:
                return False, "no indica banos"
            if l.baths < self.banos_min:
                return False, f"{l.baths} banos < {self.banos_min}"

        if self.excluir_ocupados:
            if l.occupied is True:
                return False, f"ocupado: {l.occupied_reason}"
            if l.occupied is None and not self.incluir_desconocidos:
                return False, "ocupacion no confirmada"

        return True, ""

    def apply(self, listings) -> Tuple[List[Listing], dict]:
        """Filtra una tanda y devuelve tambien el recuento de descartes por motivo."""
        pasan: List[Listing] = []
        descartes: dict = {}
        for l in listings:
            ok, motivo = self.check(l)
            if ok:
                pasan.append(l)
            else:
                clave = motivo.split(":")[0].split("(")[0].strip()
                descartes[clave] = descartes.get(clave, 0) + 1
        return pasan, descartes


def dedupe(listings: List[Listing]) -> List[List[Listing]]:
    """Agrupa el mismo inmueble anunciado en varios portales.

    Devuelve una lista de grupos; el primero de cada grupo es el "representante"
    (se prefiere Fotocasa por traer mas datos). Sirve para no mandar tres avisos
    del mismo piso.
    """
    prioridad = {"fotocasa": 0, "pisos": 1, "habitaclia": 2}
    grupos: dict = {}
    for l in listings:
        grupos.setdefault(l.fingerprint, []).append(l)
    for g in grupos.values():
        g.sort(key=lambda x: prioridad.get(x.source, 9))
    return list(grupos.values())
