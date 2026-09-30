"""Comandos de Telegram.

No hay un proceso escuchando permanentemente: cada ejecucion programada lee los
mensajes pendientes con getUpdates, los contesta y guarda el offset. Por eso un
comando tarda, como maximo, lo que tarde en llegar el siguiente ciclo.

Seguridad: solo se atiende al chat_id configurado. El token de un bot puede
acabar expuesto de muchas maneras, y sin esta comprobacion cualquiera que diera
con el bot podria lanzar barridos contra los portales en tu nombre.
"""
from __future__ import annotations

import html
import logging
from typing import List

from .models import Change

log = logging.getLogger("radar.commands")

AYUDA = """<b>Radar inmobiliario</b>

/buscar — barrido ahora mismo y te digo lo que salga
/listar — los 10 más baratos que cumplen tus criterios
/estado — cuántos anuncios sigo y cómo fue la última pasada
/criterios — qué estoy buscando exactamente
/ayuda — esta lista

Aparte de esto te aviso solo, sin que preguntes, cuando aparezca algo nuevo o cambie un precio."""


class Commands:
    def __init__(self, agent):
        self.agent = agent
        self.tg = agent.telegram
        self.store = agent.store

    def procesar_pendientes(self, max_comandos: int = 5) -> int:
        """Lee los mensajes nuevos y los responde. Devuelve cuantos atendio."""
        if not self.tg.configurado:
            log.warning("Telegram sin configurar; no se leen comandos")
            return 0

        offset = self.store.get_meta("telegram_offset")
        updates = self.tg.leer_updates(int(offset) if offset else None)
        if not updates:
            return 0

        # El offset se guarda pase lo que pase: si un comando falla, no queremos
        # que se reintente en bucle en cada ciclo.
        self.store.set_meta("telegram_offset", updates[-1]["update_id"] + 1)

        atendidos = 0
        for upd in updates:
            msg = upd.get("message") or {}
            texto = (msg.get("text") or "").strip()
            chat = str((msg.get("chat") or {}).get("id", ""))

            if not texto.startswith("/"):
                continue
            if chat != str(self.tg.chat_id):
                log.warning("comando ignorado, viene del chat %s y no del tuyo", chat)
                continue
            if atendidos >= max_comandos:
                log.warning("demasiados comandos en cola; el resto se ignora")
                break

            self._ejecutar(texto)
            atendidos += 1

        return atendidos

    # ------------------------------------------------------------------ comandos

    def _ejecutar(self, texto: str) -> None:
        # "/buscar@mi_bot 5" -> ("buscar", ["5"])
        partes = texto.lstrip("/").split()
        orden = partes[0].split("@")[0].lower()
        args = partes[1:]
        log.info("comando recibido: /%s %s", orden, " ".join(args))

        rutas = {
            "buscar": self._buscar,
            "listar": self._listar,
            "estado": self._estado,
            "criterios": self._criterios,
            "ayuda": self._ayuda,
            "start": self._ayuda,
            "help": self._ayuda,
        }
        funcion = rutas.get(orden)
        if not funcion:
            self.tg.enviar(f"No conozco /{orden}.\n\n{AYUDA}")
            return
        try:
            funcion(args)
        except Exception as e:
            log.exception("fallo ejecutando /%s", orden)
            self.tg.enviar(f"Algo ha fallado con /{orden}: {e}")

    def _buscar(self, args: List[str]) -> None:
        self.tg.enviar("Buscando... te digo algo en un minuto.")
        cambios: List[Change] = self.agent.run(modo="rapido", notificar=False)
        if cambios:
            self.tg.enviar_cambios(
                cambios,
                resumen=f"<b>Resultado de tu búsqueda</b>\n"
                        f"{sum(1 for c in cambios if c.kind == 'nuevo')} nuevos · "
                        f"{sum(1 for c in cambios if c.kind == 'precio')} cambios de precio")
        else:
            total = len(self.store.active_listings())
            self.tg.enviar(f"Nada nuevo. Sigo vigilando {total} anuncios que cumplen "
                           f"tus criterios.")

    def _listar(self, args: List[str]) -> None:
        cuantos = _entero(args[0], 10) if args else 10
        cuantos = max(1, min(cuantos, 25))
        filas = self.store.active_listings()[:cuantos]
        if not filas:
            self.tg.enviar("Ahora mismo no tengo ningún anuncio que cumpla.")
            return

        lineas = [f"<b>Los {len(filas)} más baratos que cumplen</b>"]
        for r in filas:
            precio = f"{r['price']:,}".replace(",", ".") if r["price"] else "s/p"
            sitio = r["municipality"] or r["province"] or ""
            metros = f" · {r['area']} m²" if r["area"] else ""
            aviso = "  ⚠️ ocupación sin confirmar" if r["occupied"] is None else ""
            lineas.append(
                f"\n<a href=\"{html.escape(r['url'], quote=True)}\">"
                f"{precio} € · {r['rooms']}d/{r['baths']}b{metros}</a>"
                f"\n{html.escape(sitio)}{aviso}")

        for trozo in _trocear(lineas):
            self.tg.enviar(trozo)

    def _estado(self, args: List[str]) -> None:
        import datetime as dt

        s = self.store.stats()
        lineas = [f"<b>Estado</b>",
                  f"{s['coinciden']} anuncios te encajan ahora mismo",
                  f"{s['activos']} en seguimiento, "
                  f"{s['ocupados']} descartados por estar ocupados"]

        filas = self.store.db.execute(
            "SELECT * FROM runs ORDER BY ts DESC LIMIT 6").fetchall()
        if filas:
            lineas.append("\n<b>Últimas pasadas</b>")
            for r in filas:
                cuando = dt.datetime.fromtimestamp(r["ts"]).strftime("%d/%m %H:%M")
                estado = f"ERROR {r['error'][:40]}" if r["error"] else \
                    f"{r['matched']} cumplen, {r['nuevos']} nuevos"
                lineas.append(f"{cuando} · {r['source']} · {estado}")
        self.tg.enviar("\n".join(lineas))

    def _criterios(self, args: List[str]) -> None:
        f = self.agent.filtros
        provincias = ", ".join(f.get("provincias") or [])
        precio = f"{f.get('precio_max', 0):,}".replace(",", ".")
        ocupados = "excluidos" if f.get("excluir_ocupados") else "incluidos"
        desconocida = ("se avisa con ⚠️" if f.get("incluir_ocupacion_desconocida")
                       else "se descartan")
        self.tg.enviar(
            f"<b>Lo que estoy buscando</b>\n"
            f"Provincias: {provincias}\n"
            f"Precio máximo: {precio} €\n"
            f"Dormitorios: {f.get('dormitorios_min')} o más\n"
            f"Baños: {f.get('banos_min')} o más\n"
            f"Ocupados: {ocupados}\n"
            f"Ocupación sin confirmar: {desconocida}\n\n"
            f"Portales: Fotocasa, pisos.com y Habitaclia.")

    def _ayuda(self, args: List[str]) -> None:
        self.tg.enviar(AYUDA)


def _entero(texto: str, defecto: int) -> int:
    try:
        return int(texto)
    except (TypeError, ValueError):
        return defecto


def _trocear(lineas: List[str], limite: int = 3800) -> List[str]:
    mensajes, actual = [], ""
    for l in lineas:
        if actual and len(actual) + len(l) + 1 > limite:
            mensajes.append(actual)
            actual = l
        else:
            actual = f"{actual}\n{l}" if actual else l
    if actual:
        mensajes.append(actual)
    return mensajes
