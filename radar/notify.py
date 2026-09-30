"""Notificacion por Telegram.

Telegram limita los mensajes a 4096 caracteres, asi que los avisos se agrupan
en varios mensajes en vez de recortarse. El formato es HTML, que es el que
mejor tolera nombres de calle con caracteres raros.
"""
from __future__ import annotations

import html
import logging
import os
import time
from typing import Iterable, List, Optional

import requests

from .models import Change

log = logging.getLogger("radar.notify")

API = "https://api.telegram.org/bot{token}/{method}"
LIMITE = 3800   # margen sobre los 4096 de Telegram


class Telegram:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def enviar(self, texto: str) -> bool:
        if not self.configurado:
            log.warning("Telegram sin configurar; no se envia nada")
            return False
        try:
            r = requests.post(
                API.format(token=self.token, method="sendMessage"),
                json={"chat_id": self.chat_id, "text": texto,
                      "parse_mode": "HTML", "disable_web_page_preview": False},
                timeout=20)
            if r.status_code == 429:
                espera = r.json().get("parameters", {}).get("retry_after", 5)
                log.warning("Telegram pide esperar %ss", espera)
                time.sleep(espera + 1)
                return self.enviar(texto)
            if not r.ok:
                log.error("Telegram %s: %s", r.status_code, r.text[:300])
                return False
            return True
        except requests.RequestException as e:
            log.error("Telegram no responde: %s", e)
            return False

    def enviar_cambios(self, cambios: List[Change], resumen: str = "") -> bool:
        """Manda los avisos troceados para no chocar con el limite de Telegram."""
        if not cambios:
            return True

        nuevos = [c for c in cambios if c.kind == "nuevo"]
        precios = [c for c in cambios if c.kind == "precio"]

        bloques: List[str] = []
        cabecera = resumen or (f"<b>Radar inmobiliario</b>\n"
                               f"{len(nuevos)} nuevos · {len(precios)} cambios de precio")
        bloques.append(cabecera)

        if nuevos:
            bloques.append("\n<b>NUEVOS ANUNCIOS</b>")
            bloques.extend(_ficha(c) for c in nuevos)
        if precios:
            bloques.append("\n<b>CAMBIOS DE PRECIO</b>")
            bloques.extend(_ficha(c) for c in sorted(
                precios, key=lambda c: c.delta if c.delta is not None else 0))

        ok = True
        for mensaje in _agrupar(bloques, LIMITE):
            ok = self.enviar(mensaje) and ok
            time.sleep(0.5)   # cortesia con la API
        return ok

    def leer_updates(self, offset: Optional[int] = None) -> List[dict]:
        """Descarga los mensajes pendientes dirigidos al bot.

        `offset` es el id del ultimo update ya procesado mas uno; Telegram
        descarta del servidor todo lo anterior, asi que guardarlo es lo que
        evita responder dos veces al mismo comando.
        """
        if not self.token:
            return []
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        try:
            r = requests.get(API.format(token=self.token, method="getUpdates"),
                             params=params, timeout=25)
            r.raise_for_status()
            return r.json().get("result", [])
        except (requests.RequestException, ValueError) as e:
            log.error("no se pudieron leer los mensajes: %s", e)
            return []

    def resolver_chat_id(self) -> List[dict]:
        """Lee getUpdates para averiguar el chat_id tras escribirle al bot."""
        r = requests.get(API.format(token=self.token, method="getUpdates"), timeout=20)
        r.raise_for_status()
        chats = {}
        for upd in r.json().get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id"):
                chats[chat["id"]] = chat
        return list(chats.values())


def _ficha(c: Change) -> str:
    l = c.listing
    partes = []

    if c.kind == "precio":
        flecha = "BAJA" if (c.delta or 0) < 0 else "SUBE"
        # El separador de miles se pone aparte: aplicar .replace(",", ".") sobre
        # la linea entera convertiria tambien la coma que separa los dos datos.
        salto = f"{c.delta:+,}".replace(",", ".")
        partes.append(
            f"{flecha} {_eur(c.old_price)} → <b>{_eur(c.new_price)}</b> "
            f"({salto} €, {c.delta_pct:+.1f}%)")
    else:
        partes.append(f"<b>{_eur(l.price)}</b>")

    detalles = []
    if l.rooms is not None:
        detalles.append(f"{l.rooms} dorm")
    if l.baths is not None:
        detalles.append(f"{l.baths} baños")
    if l.area:
        detalles.append(f"{l.area} m²")
    if detalles:
        partes.append(" · ".join(detalles))

    sitio = " · ".join(x for x in (l.municipality, l.province) if x)
    titulo = html.escape(l.title or l.ptype.capitalize() or "Anuncio")

    linea = f"\n<a href=\"{html.escape(l.url, quote=True)}\">{titulo}</a>\n"
    linea += " | ".join(partes)
    if sitio:
        linea += f"\n{html.escape(sitio)}"
    marca = {"fotocasa": "Fotocasa", "pisos": "pisos.com",
             "habitaclia": "Habitaclia"}.get(l.source, l.source)
    linea += f"  <i>[{marca}]</i>"
    if l.occupied is None:
        linea += "  ⚠️ ocupacion no confirmada"
    return linea


def _agrupar(bloques: Iterable[str], limite: int) -> List[str]:
    """Junta bloques en mensajes que no superen el limite, sin partir un bloque."""
    mensajes: List[str] = []
    actual = ""
    for b in bloques:
        if actual and len(actual) + len(b) + 1 > limite:
            mensajes.append(actual)
            actual = b
        else:
            actual = f"{actual}\n{b}" if actual else b
    if actual:
        mensajes.append(actual)
    return mensajes


def _eur(v: Optional[int]) -> str:
    if v is None:
        return "s/p"
    return f"{v:,}".replace(",", ".") + " €"
