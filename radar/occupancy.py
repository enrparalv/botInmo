"""Deteccion de inmuebles ocupados a partir del texto del anuncio.

Los portales rara vez tienen un campo "ocupado" fiable (Fotocasa si, y lo
usamos con prioridad). El resto hay que deducirlo del texto, donde las
inmobiliarias y servicers usan un vocabulario bastante estable:
"sin posesion", "no visitable", "con inquilinos", "nuda propiedad"...

El orden de evaluacion importa. Un anuncio puede decir a la vez
"vivienda ocupada" y "concertar visita con la agencia", asi que las senales
inequivocas de ocupacion se comprueban ANTES que las de disponibilidad, y las
senales ambiguas (visitas) despues. Devuelve (ocupado, motivo) donde `ocupado`:
    True  -> hay evidencia de ocupacion / no disponibilidad
    False -> hay evidencia explicita de que se entrega libre
    None  -> el anuncio no dice nada (lo mas comun)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

# --- 1. Ocupacion inequivoca: gana siempre, aunque el anuncio hable de visitas.
OCUPADO_FUERTE = [
    (r"\bocupad[oa]s?\b", "marcado como ocupado"),
    (r"ocupacion ilegal", "ocupacion ilegal"),
    (r"\bokupa", "okupas"),
    (r"sin pose", "sin posesion"),
    (r"no se garantiza la posesion", "posesion no garantizada"),
    (r"posesion no garantizada", "posesion no garantizada"),
    (r"sin garantia de posesion", "posesion no garantizada"),
    (r"posesion no disponible", "posesion no disponible"),
    (r"posesion (?:no )?juridica", "solo posesion juridica"),
    (r"situacion posesoria", "situacion posesoria irregular"),
    (r"con inquilin", "con inquilinos"),
    (r"con arrendatari", "con arrendatarios"),
    (r"inquilinos? dentro", "con inquilinos"),
    (r"actualmente alquilad", "alquilado"),
    (r"actualmente arrendad", "arrendado"),
    (r"contrato de arrendamiento (?:en )?vigor", "arrendamiento vigente"),
    (r"con contrato de alquiler", "arrendamiento vigente"),
    (r"alquilado con rentabilidad", "alquilado"),
    (r"nuda propiedad", "nuda propiedad"),
    (r"con usufructo", "usufructo vitalicio"),
    (r"usufructuari", "usufructo vitalicio"),
    (r"proindiviso", "proindiviso"),
    (r"\bsubasta\b", "subasta"),
]

# --- 2. Disponibilidad explicita. Ojo con las negaciones: "no se puede visitar"
#        no debe leerse como "se puede visitar".
LIBRE_PATTERNS = [
    r"libre de ocupant",
    r"libre de inquilin",
    r"libre de cargas y ocupant",
    r"libre de arrendatari",
    r"sin ocupant",
    r"sin inquilin",
    r"desocupad",
    r"vivienda vacia",
    r"(?<!no )(?:se )?entrega (?:totalmente )?(?:libre|vacia)",
    r"entrega de llaves",
    r"llaves? (?:disponible|en la oficina|inmediata)",
    r"posesion garantizada",
    r"disponibilidad inmediata",
    r"list[oa]s? para entrar a vivir",
    r"(?<!no )se puede visitar",
    r"visitas? concertad",
    r"(?<!sin )(?<!no )concertar visita",
]

# --- 3. Senales debiles: solo cuentan si nada anterior ha decidido.
OCUPADO_DEBIL = [
    (r"no (?:se puede|es posible) visitar", "no visitable"),
    (r"no visitable", "no visitable"),
    (r"sin derecho (?:a|de) visita", "no visitable"),
    (r"no se (?:realizan|permiten|hacen) visitas", "no visitable"),
    (r"no se muestra el interior", "no visitable"),
    (r"se vende (?:tal cual|como esta|en el estado)", "venta sin posesion garantizada"),
]

_FUERTE_RE = [(re.compile(p), m) for p, m in OCUPADO_FUERTE]
_LIBRE_RE = [re.compile(p) for p in LIBRE_PATTERNS]
_DEBIL_RE = [(re.compile(p), m) for p, m in OCUPADO_DEBIL]


def normalize(text: str) -> str:
    """Minusculas y sin acentos, para que los patrones no dependan de tildes."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower())


def from_url(url: str) -> str:
    """Convierte el slug de una url en texto analizable.

    Los portales meten el titular del anuncio en la url, y ahi sobrevive
    informacion que la tarjeta recorta con puntos suspensivos. Por ejemplo
    '..._activo_inmobiliario_sin_posesion-cartaya-i243...htm' delata un
    inmueble sin posesion que la descripcion truncada no llegaba a mostrar.
    """
    if not url:
        return ""
    slug = re.sub(r"^https?://[^/]+/", "", url)
    slug = re.sub(r"\.(htm|html)$", "", slug)
    return re.sub(r"[_\-/]+", " ", slug)


def detect(*texts: str) -> Tuple[Optional[bool], str]:
    """Analiza titulo + descripcion + etiquetas y decide el estado de ocupacion."""
    blob = normalize(" ".join(t for t in texts if t))
    if not blob:
        return None, ""

    for rx, motivo in _FUERTE_RE:
        m = rx.search(blob)
        if m:
            return True, f"{motivo} ('{m.group(0)}')"

    for rx in _LIBRE_RE:
        m = rx.search(blob)
        if m:
            return False, f"libre: '{m.group(0)}'"

    for rx, motivo in _DEBIL_RE:
        m = rx.search(blob)
        if m:
            return True, f"{motivo} ('{m.group(0)}')"

    return None, ""


def combine(flag: Optional[bool], flag_reason: str,
            text_result: Tuple[Optional[bool], str]) -> Tuple[Optional[bool], str]:
    """Une un flag estructurado del portal con el analisis de texto.

    El flag del portal manda cuando afirma ocupacion; el texto solo se usa
    para rellenar el hueco o para confirmar.
    """
    text_flag, text_reason = text_result
    if flag is True:
        return True, flag_reason or "marcado por el portal"
    if text_flag is True:
        return True, text_reason
    if flag is False:
        return False, flag_reason or "el portal lo marca como libre"
    return text_flag, text_reason
