"""Prueba los tres parsers contra HTML real guardado en disco.

Uso:  python test_parsers.py [carpeta_con_fc.html_pi.html_ha.html]
Si no hay ficheros guardados, los descarga.
"""
import sys
from pathlib import Path

from radar.http import Fetcher
from radar.sources.fotocasa import Fotocasa
from radar.sources.habitaclia import Habitaclia
from radar.sources.pisos import Pisos

URLS = {
    "fc.html": "https://www.fotocasa.es/es/comprar/viviendas/huelva-provincia/todas-las-zonas/l",
    "pi.html": "https://www.pisos.com/venta/pisos-huelva/",
    "ha.html": "https://www.habitaclia.com/viviendas-huelva.htm",
}


def load(cache: Path, name: str) -> str:
    f = cache / name
    if not f.exists():
        print(f"  descargando {URLS[name]} ...")
        cache.mkdir(parents=True, exist_ok=True)
        html = Fetcher(delay=1.0).get(URLS[name])
        f.write_text(html or "", encoding="utf-8")
    return f.read_text(encoding="utf-8", errors="replace")


def show(label, listings):
    print(f"\n=== {label}: {len(listings)} anuncios parseados ===")
    ok = sum(1 for l in listings if l.price and l.rooms is not None and l.baths is not None)
    print(f"    con precio+dorm+banos completos: {ok}/{len(listings)}")
    for l in listings[:6]:
        precio = f"{l.price:,}".replace(",", ".") + " EUR" if l.price else "sin precio"
        print(f"  {precio:>13} | {l.rooms}d {l.baths}b {l.area}m2 | {l.ptype or '?':<10} "
              f"| {l.municipality[:16]:<16} | occ={l.occupied}")
        print(f"       {l.title[:70]}")
        print(f"       {l.url[:95]}")
    faltan = [l for l in listings if not l.price or l.rooms is None or l.baths is None]
    if faltan:
        print(f"    !! {len(faltan)} incompletos, p.ej.: "
              f"precio={faltan[0].price} rooms={faltan[0].rooms} baths={faltan[0].baths} "
              f"title={faltan[0].title[:40]!r}")


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/cache_test")
    f = Fetcher(delay=1.0)

    res = Fotocasa._extract(load(cache, "fc.html"))
    src = Fotocasa({"provincias": {}}, f)
    show("Fotocasa", [x for x in (src._parse(r, "Huelva") for r in res["realEstates"]) if x])

    src = Pisos({"provincias": {}}, f)
    show("pisos.com", list(src._parse_page(load(cache, "pi.html"), "Huelva")))

    src = Habitaclia({"municipios": {}}, f)
    show("Habitaclia", list(src._parse_page(load(cache, "ha.html"), "Huelva", "huelva")))


if __name__ == "__main__":
    main()
