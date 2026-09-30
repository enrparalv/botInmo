"""Radar inmobiliario: vigila anuncios en Huelva y Sevilla.

Comandos:
    python run.py vigilar              barrido rapido (lo nuevo). Para el cron.
    python run.py vigilar --completo   barrido entero: precios y anuncios retirados.
    python run.py vigilar --sin-avisar prueba sin mandar nada a Telegram.
    python run.py estado               que hay en la base de datos ahora mismo.
    python run.py listar               los anuncios que cumplen, ordenados por precio.
    python run.py bot                  lee y contesta los comandos de Telegram.
    python run.py verificar            abre fichas y confirma que no estan ocupadas.
    python run.py telegram-setup       averigua tu chat_id y manda un mensaje de prueba.
    python run.py probar-fuentes       comprueba que los tres portales siguen legibles.
"""
from __future__ import annotations

import argparse
import logging
import sys

from radar.agent import Agent, cargar_config, cargar_env
from radar.http import Fetcher
from radar.notify import Telegram
from radar.sources import REGISTRY


def _utf8() -> None:
    """Fuerza UTF-8 en la salida.

    Las tareas programadas redirigen a data\\radar.log y la consola de Windows
    usa cp1252 por defecto, asi que cualquier nombre con tilde (Ecija, Punta
    Umbria) o un simbolo como -> abortaba la ejecucion con UnicodeEncodeError.

    De paso se fuerza el volcado linea a linea: al redirigir a un fichero Python
    acumula la salida en bloques, y en un barrido de media hora eso significa
    quedarse mirando un log vacio sin saber si avanza o se ha colgado.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout)


def cmd_vigilar(args) -> int:
    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        modo = "completo" if args.completo else "rapido"
        cambios = agente.run(modo=modo, notificar=not args.sin_avisar,
                             solo_fuente=args.fuente)
        nuevos = sum(1 for c in cambios if c.kind == "nuevo")
        precios = sum(1 for c in cambios if c.kind == "precio")
        print(f"\n=> {nuevos} anuncios nuevos, {precios} cambios de precio")
        for c in cambios[:30]:
            l = c.listing
            if c.kind == "precio":
                print(f"  PRECIO {c.old_price:>8} -> {c.new_price:<8} "
                      f"({c.delta_pct:+.1f}%)  {l.municipality:<18} {l.url}")
            else:
                print(f"  NUEVO  {str(l.price):>8}  {l.rooms}d/{l.baths}b  "
                      f"{l.municipality:<18} {l.url}")
        if len(cambios) > 30:
            print(f"  ... y {len(cambios) - 30} mas")
        return 0
    finally:
        agente.close()


def cmd_estado(args) -> int:
    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        s = agente.store.stats()
        print(f"Anuncios en seguimiento : {s['total']}")
        print(f"  activos               : {s['activos']}")
        print(f"  marcados como ocupados: {s['ocupados']}")
        print(f"Telegram configurado    : {'si' if agente.telegram.configurado else 'NO'}")
        print("\nUltimas ejecuciones:")
        filas = agente.store.db.execute(
            "SELECT * FROM runs ORDER BY ts DESC LIMIT 12").fetchall()
        for r in filas:
            import datetime as dt
            cuando = dt.datetime.fromtimestamp(r["ts"]).strftime("%d/%m %H:%M")
            err = f"  ERROR: {r['error'][:60]}" if r["error"] else ""
            print(f"  {cuando}  {r['mode']:<9} {r['source']:<22} "
                  f"vistos={r['seen']:<5} cumplen={r['matched']:<5} "
                  f"nuevos={r['nuevos']:<4} precio={r['cambios']}{err}")
        return 0
    finally:
        agente.close()


def cmd_listar(args) -> int:
    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        filas = agente.store.active_listings()
        print(f"{len(filas)} anuncios activos que cumplen tus criterios\n")
        for r in filas[:args.limite]:
            precio = f"{r['price']:,}".replace(",", ".") if r["price"] else "s/p"
            ocup = {1: "OCUPADO", 0: "libre"}.get(r["occupied"], "?")
            print(f"{precio:>10} EUR | {r['rooms']}d {r['baths']}b "
                  f"{str(r['area'] or '?'):>4}m2 | {ocup:<8} | "
                  f"{(r['municipality'] or '')[:20]:<20} | {r['source']:<11} {r['url']}")
        return 0
    finally:
        agente.close()


def cmd_ciclo(args) -> int:
    """Atiende comandos y escanea si toca. Es lo que ejecuta GitHub Actions."""
    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        r = agente.ciclo(forzar=args.forzar or "")
        print(f"\n=> {r['comandos']} comando(s) atendido(s), "
              f"barrido: {r['modo']}, {r['cambios']} cambio(s)")
        return 0
    finally:
        agente.close()


def cmd_bot(args) -> int:
    """Lee los comandos que le hayas escrito al bot y los contesta."""
    from radar.commands import Commands

    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        atendidos = Commands(agente).procesar_pendientes()
        print(f"{atendidos} comando(s) atendido(s)")
        return 0
    finally:
        agente.close()


def cmd_verificar(args) -> int:
    """Abre la ficha de los anuncios con ocupacion desconocida y la confirma."""
    from radar.agent import _texto_visible
    from radar import occupancy

    cfg = cargar_config(args.config)
    agente = Agent(cfg, args.db)
    try:
        filas = agente.store.db.execute(
            "SELECT key, url FROM listings WHERE active = 1 AND occupied IS NULL "
            "ORDER BY price ASC LIMIT ?", (args.limite,)).fetchall()
        print(f"Verificando {len(filas)} fichas (unos {len(filas) * 2 // 60} min)...\n")

        ocupados = libres = sin_dato = 0
        for i, r in enumerate(filas, 1):
            doc = agente.fetcher.get(r["url"])
            if not doc:
                sin_dato += 1
                continue
            occ, motivo = occupancy.detect(_texto_visible(doc))
            if occ is None:
                sin_dato += 1
                continue
            agente.store.db.execute(
                "UPDATE listings SET occupied = ?, occupied_reason = ? WHERE key = ?",
                (int(occ), motivo, r["key"]))
            if occ:
                ocupados += 1
                print(f"  [{i}/{len(filas)}] OCUPADO  {motivo:<40} {r['url'][:70]}")
            else:
                libres += 1
        agente.store.db.commit()

        print(f"\n=> {libres} libres, {ocupados} ocupados (descartados), "
              f"{sin_dato} sin informacion en la ficha")
        if ocupados:
            print("Los ocupados quedan marcados y ya no apareceran en 'listar'.")
        return 0
    finally:
        agente.close()


def cmd_telegram_setup(args) -> int:
    tg = Telegram()
    if not tg.token:
        print("Falta TELEGRAM_BOT_TOKEN en .env\n")
        print("Como conseguirlo:")
        print("  1. Abre Telegram y habla con @BotFather")
        print("  2. Envia /newbot y sigue los pasos")
        print("  3. Copia el token en .env  ->  TELEGRAM_BOT_TOKEN=123456:ABC-...")
        print("  4. Escribele CUALQUIER mensaje a tu bot nuevo (p.ej. 'hola')")
        print("  5. Vuelve a ejecutar: python run.py telegram-setup")
        return 1

    if not tg.chat_id:
        print("Buscando tu chat_id... (tienes que haberle escrito al bot antes)")
        chats = tg.resolver_chat_id()
        if not chats:
            print("\nNo he visto ningun mensaje. Escribele algo a tu bot en Telegram "
                  "y vuelve a ejecutar este comando.")
            return 1
        print("\nChats encontrados:")
        for c in chats:
            quien = c.get("username") or c.get("title") or c.get("first_name") or "?"
            print(f"  chat_id={c['id']}   ({quien})")
        print(f"\nPon esto en .env  ->  TELEGRAM_CHAT_ID={chats[0]['id']}")
        return 0

    print(f"Token y chat_id presentes. Enviando mensaje de prueba a {tg.chat_id}...")
    ok = tg.enviar("<b>Radar inmobiliario</b>\nConexion correcta. "
                   "Te avisare de pisos nuevos y bajadas de precio en Huelva y Sevilla.")
    print("Enviado, mira tu Telegram." if ok else "No se pudo enviar; revisa el token.")
    return 0 if ok else 1


def cmd_probar_fuentes(args) -> int:
    """Comprueba que cada portal sigue devolviendo anuncios parseables."""
    cfg = cargar_config(args.config)
    f = Fetcher(delay=1.5)
    provincia = (cfg["filtros"]["provincias"] or ["Huelva"])[0]
    fallos = 0

    for nombre, clase in REGISTRY.items():
        fcfg = (cfg.get("fuentes") or {}).get(nombre) or {}
        if not fcfg.get("activa", True):
            print(f"{nombre:<12} desactivada en config.json")
            continue
        fuente = clase(fcfg, f)
        try:
            muestra = []
            for lst in fuente.scan(provincia, cfg["filtros"], 1, newest_first=True):
                muestra.append(lst)
                if len(muestra) >= 40:
                    break
            completos = sum(1 for l in muestra
                            if l.price and l.rooms is not None and l.baths is not None)
            estado = "OK " if muestra else "SIN RESULTADOS"
            print(f"{nombre:<12} {estado} {len(muestra)} anuncios, "
                  f"{completos} con datos completos")
            if muestra:
                l = muestra[0]
                print(f"             ej: {l.price} EUR, {l.rooms}d/{l.baths}b, "
                      f"{l.municipality}, occ={l.occupied}")
            else:
                fallos += 1
        except Exception as e:
            print(f"{nombre:<12} ERROR: {e}")
            fallos += 1
    return 1 if fallos else 0


def main() -> int:
    _utf8()
    cargar_env()
    p = argparse.ArgumentParser(
        description="Vigilancia de anuncios inmobiliarios en Huelva y Sevilla",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--config", default="config.json")
    p.add_argument("--db", default="data/radar.db")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("vigilar", help="buscar novedades y avisar")
    v.add_argument("--completo", action="store_true",
                   help="barrido entero (mas lento): tambien precios y bajas")
    v.add_argument("--sin-avisar", action="store_true",
                   help="no manda nada a Telegram")
    v.add_argument("--fuente", choices=list(REGISTRY),
                   help="limitar a un solo portal")
    v.set_defaults(func=cmd_vigilar)

    e = sub.add_parser("estado", help="resumen de la base de datos")
    e.set_defaults(func=cmd_estado)

    l = sub.add_parser("listar", help="anuncios activos que cumplen")
    l.add_argument("--limite", type=int, default=50)
    l.set_defaults(func=cmd_listar)

    ci = sub.add_parser("ciclo",
                        help="atender comandos y escanear si toca (GitHub Actions)")
    ci.add_argument("--forzar", choices=["rapido", "completo"],
                    help="escanear ahora, sin esperar al intervalo")
    ci.set_defaults(func=cmd_ciclo)

    b = sub.add_parser("bot", help="leer y contestar los comandos de Telegram")
    b.set_defaults(func=cmd_bot)

    ve = sub.add_parser("verificar",
                        help="abrir fichas para confirmar que no estan ocupadas")
    ve.add_argument("--limite", type=int, default=100)
    ve.set_defaults(func=cmd_verificar)

    t = sub.add_parser("telegram-setup", help="configurar y probar Telegram")
    t.set_defaults(func=cmd_telegram_setup)

    s = sub.add_parser("probar-fuentes", help="comprobar que los portales se leen bien")
    s.set_defaults(func=cmd_probar_fuentes)

    args = p.parse_args()
    _log(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
