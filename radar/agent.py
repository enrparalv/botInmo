"""Orquestacion: barrer las fuentes, filtrar, guardar y avisar."""
from __future__ import annotations

import html as htmllib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List

from . import occupancy
from .filters import Filtro, dedupe
from .http import Fetcher
from .models import Change
from .notify import Telegram
from .sources import REGISTRY
from .store import Store

log = logging.getLogger("radar.agent")


def cargar_config(path="config.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cargar_env(path=".env") -> None:
    """Lee un .env sencillo y lo mete en el entorno, sin dependencias externas."""
    f = Path(path)
    if not f.exists():
        return
    for linea in f.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


class Agent:
    def __init__(self, config: dict, db_path="data/radar.db"):
        self.cfg = config
        self.filtros = config.get("filtros", {})
        self.escaneo = config.get("escaneo", {})
        self.store = Store(db_path)
        self.filtro = Filtro(self.filtros)
        self.fetcher = Fetcher(
            delay=float(self.escaneo.get("segundos_entre_peticiones", 2.0)),
            retries=int(self.escaneo.get("reintentos", 3)))
        self.telegram = Telegram()

    def close(self) -> None:
        self.store.close()

    def run(self, modo="rapido", notificar=True, solo_fuente=None) -> List[Change]:
        """Un ciclo completo de vigilancia.

        modo 'rapido'  -> primeras paginas ordenadas por fecha: pilla lo nuevo.
        modo 'completo'-> barrido entero: ademas detecta cambios de precio y bajas.
        """
        completo = modo == "completo"
        max_pages = int(self.escaneo.get(
            "paginas_completo" if completo else "paginas_rapido", 5))
        provincias = self.filtros.get("provincias") or []
        primera_vez = self.store.is_first_run()

        if primera_vez:
            log.info("Primera ejecucion: se construye la linea base "
                     "y NO se notifica el catalogo entero.")

        todos_cambios: List[Change] = []
        salud: dict = {}

        for nombre, clase in REGISTRY.items():
            fcfg = (self.cfg.get("fuentes") or {}).get(nombre) or {}
            if not fcfg.get("activa", True):
                continue
            if solo_fuente and nombre != solo_fuente:
                continue
            if not completo and not clase.ordena_por_fecha and not solo_fuente:
                log.debug("%s no admite orden por fecha: se deja para el "
                          "barrido completo", nombre)
                continue

            fuente = clase(fcfg, self.fetcher)
            for provincia in provincias:
                vistos, pasan = 0, []
                inicio = time.time()
                try:
                    for lst in fuente.scan(provincia, self.filtros, max_pages,
                                           newest_first=not completo):
                        vistos += 1
                        ok, _ = self.filtro.check(lst)
                        if ok:
                            pasan.append(lst)
                except Exception as e:                      # una fuente rota no
                    log.exception("fallo en %s/%s: %s", nombre, provincia, e)
                    self.store.log_run(modo, f"{nombre}/{provincia}", vistos,
                                       len(pasan), 0, 0, str(e)[:200])
                    continue                                # no tumba el resto

                cambios = self.store.upsert_many(pasan)
                nuevos = sum(1 for c in cambios if c.kind == "nuevo")
                precios = sum(1 for c in cambios if c.kind == "precio")

                # Dar un anuncio por retirado solo es legitimo si de verdad se
                # recorrio el listado entero. Si el barrido se corto por el tope
                # de paginas o por un fallo de red, los que no aparecieron
                # simplemente no se miraron: marcarlos de baja los borraria del
                # seguimiento sin motivo.
                if completo and pasan and fuente.completado:
                    bajas = self.store.mark_inactive(
                        nombre, {l.key for l in pasan}, provincia)
                    if bajas:
                        log.info("%s/%s: %s anuncios retirados", nombre, provincia, len(bajas))
                elif completo and not fuente.completado:
                    log.warning("%s/%s: barrido incompleto, no se dan de baja anuncios",
                                nombre, provincia)

                log.info("%s/%s: %s vistos, %s cumplen, %s nuevos, %s cambios de precio (%.0fs)",
                         nombre, provincia, vistos, len(pasan), nuevos, precios,
                         time.time() - inicio)
                self.store.log_run(modo, f"{nombre}/{provincia}", vistos,
                                   len(pasan), nuevos, precios)
                salud[nombre] = salud.get(nombre, 0) + vistos
                todos_cambios.extend(cambios)

        self._avisar_fuentes_mudas(salud, notificar)

        if primera_vez:
            log.info("Linea base guardada: %s anuncios. A partir de ahora solo "
                     "se avisa de lo que cambie.", len(todos_cambios))
            return []

        todos_cambios = self._quitar_duplicados(todos_cambios)
        todos_cambios = self._verificar_ocupacion(todos_cambios)

        if notificar and todos_cambios:
            if self.telegram.configurado:
                if self.telegram.enviar_cambios(todos_cambios):
                    self.store.mark_notified(c.listing.key for c in todos_cambios)
                    log.info("Notificados %s cambios por Telegram", len(todos_cambios))
            else:
                log.warning("Hay %s cambios pero Telegram no esta configurado "
                            "(revisa .env)", len(todos_cambios))

        return todos_cambios

    def ciclo(self, forzar: str = "") -> dict:
        """Una pasada completa de mantenimiento, pensada para GitHub Actions.

        Atiende los comandos de Telegram y decide por su cuenta si toca escanear,
        segun cuanto haya pasado desde la ultima vez. De este modo basta con un
        unico workflow ejecutandose a intervalo fijo: no hay dos procesos
        escribiendo el estado a la vez ni riesgo de pisarse.

        `forzar` puede ser 'rapido' o 'completo' para saltarse los intervalos.
        """
        from .commands import Commands

        resultado = {"comandos": 0, "modo": "ninguno", "cambios": 0}
        resultado["comandos"] = Commands(self).procesar_pendientes()

        ahora = time.time()
        intervalos = self.cfg.get("intervalos", {})
        min_rapido = float(intervalos.get("minutos_entre_rapidos", 60)) * 60
        min_completo = float(intervalos.get("horas_entre_completos", 24)) * 3600

        ultimo_rapido = float(self.store.get_meta("ultimo_rapido", 0) or 0)
        ultimo_completo = float(self.store.get_meta("ultimo_completo", 0) or 0)

        if forzar:
            modo = forzar
        elif ahora - ultimo_completo >= min_completo:
            modo = "completo"
        elif ahora - ultimo_rapido >= min_rapido:
            modo = "rapido"
        else:
            faltan = int((min_rapido - (ahora - ultimo_rapido)) / 60)
            log.info("Aun no toca escanear; faltan unos %s min", faltan)
            return resultado

        log.info("Barrido %s", modo)
        cambios = self.run(modo=modo)
        resultado["modo"] = modo
        resultado["cambios"] = len(cambios)

        self.store.set_meta("ultimo_rapido", ahora)
        if modo == "completo":
            self.store.set_meta("ultimo_completo", ahora)
        return resultado

    def _avisar_fuentes_mudas(self, salud: dict, notificar: bool) -> None:
        """Avisa si un portal ha dejado de devolver anuncios.

        El fallo mas probable al ejecutar esto fuera de casa es que un portal
        empiece a bloquear la IP del centro de datos, o que cambie su HTML. En
        ambos casos la fuente deja de leer sin lanzar ningun error, y el radar
        se quedaria callado aparentando normalidad. Mejor decirlo.
        """
        mudas = [n for n, vistos in salud.items() if vistos == 0]
        if not mudas:
            self.store.set_meta("fuentes_mudas", "")
            return

        log.error("fuentes sin resultados: %s", ", ".join(mudas))
        # No repetir el mismo aviso en cada ciclo mientras el problema persista.
        if self.store.get_meta("fuentes_mudas", "") == ",".join(sorted(mudas)):
            return
        self.store.set_meta("fuentes_mudas", ",".join(sorted(mudas)))

        if notificar and self.telegram.configurado:
            self.telegram.enviar(
                "<b>Aviso: una fuente ha dejado de responder</b>\n"
                f"Sin resultados en: {', '.join(mudas)}.\n\n"
                "Suele significar que el portal ha bloqueado la IP o que ha "
                "cambiado su maquetado. Los demás portales siguen funcionando.")

    def _verificar_ocupacion(self, cambios: List[Change]) -> List[Change]:
        """Confirma en la ficha completa que el inmueble no esta ocupado.

        Las tarjetas del listado recortan la descripcion con puntos suspensivos,
        y ahi es justo donde suele estar la letra pequena ("sin posesion",
        "no visitable"). Como esto solo se hace con los pocos anuncios que
        estan a punto de notificarse, el coste en peticiones es minimo y evita
        el peor fallo posible: avisarte de un piso ocupado.
        """
        if not self.filtro.excluir_ocupados or not cambios:
            return cambios

        limite = int(self.escaneo.get("max_verificaciones", 40))
        pendientes = [c for c in cambios if c.listing.occupied is None][:limite]
        if not pendientes:
            return cambios

        log.info("Verificando la ficha completa de %s anuncios...", len(pendientes))
        descartados = set()

        for c in pendientes:
            doc = self.fetcher.get(c.listing.url)
            if not doc:
                continue
            texto = _texto_visible(doc)
            occ, motivo = occupancy.detect(texto)
            if occ is not None:
                c.listing.occupied = occ
                c.listing.occupied_reason = motivo
            if occ is True:
                log.info("descartado por la ficha (%s): %s", motivo, c.listing.url)
                descartados.add(c.listing.key)

        if descartados:
            self.store.upsert_many([c.listing for c in pendientes])
        return [c for c in cambios if c.listing.key not in descartados]

    @staticmethod
    def _quitar_duplicados(cambios: List[Change]) -> List[Change]:
        """Un mismo piso en dos portales genera un solo aviso."""
        if not cambios:
            return cambios
        por_tipo: dict = {}
        for c in cambios:
            por_tipo.setdefault(c.kind, []).append(c)

        salida: List[Change] = []
        for kind, grupo in por_tipo.items():
            vistos = set()
            for g in dedupe([c.listing for c in grupo]):
                representante = g[0]
                if representante.key in vistos:
                    continue
                vistos.add(representante.key)
                salida.append(next(c for c in grupo
                                   if c.listing.key == representante.key))
        return salida


_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _texto_visible(doc: str) -> str:
    """Extrae el texto legible de una ficha, sin scripts ni etiquetas."""
    doc = _SCRIPT_RE.sub(" ", doc)
    return htmllib.unescape(_TAG_RE.sub(" ", doc))
