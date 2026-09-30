"""Persistencia en SQLite: estado actual de cada anuncio e historico de precios.

La deteccion de cambios vive aqui: `upsert_many` compara lo que acaba de
llegar del portal con lo guardado y devuelve la lista de novedades.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Change, Listing

#: Cuanto texto de la descripcion se guarda. La deteccion de ocupacion trabaja
#: sobre el texto recien descargado, no sobre el guardado, y la verificacion
#: vuelve a bajar la ficha entera. O sea que esto solo sirve para poder mirar
#: por encima un anuncio desde la base de datos. Guardar 2000 caracteres por
#: anuncio inflaba la base a 7 MB, y en GitHub Actions eso se sube en cada pasada.
MAX_DESC = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key             TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT,
    price           INTEGER,
    rooms           INTEGER,
    baths           INTEGER,
    area            INTEGER,
    municipality    TEXT,
    province        TEXT,
    ptype           TEXT,
    occupied        INTEGER,
    occupied_reason TEXT,
    description     TEXT,
    agency          TEXT,
    fingerprint     TEXT,
    first_seen      REAL NOT NULL,
    last_seen       REAL NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    notified        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_listings_fp     ON listings(fingerprint);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(active);

CREATE TABLE IF NOT EXISTS price_history (
    key   TEXT NOT NULL,
    ts    REAL NOT NULL,
    price INTEGER,
    PRIMARY KEY (key, ts)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    ts       REAL PRIMARY KEY,
    mode     TEXT,
    source   TEXT,
    seen     INTEGER,
    matched  INTEGER,
    nuevos   INTEGER,
    cambios  INTEGER,
    error    TEXT
);
"""


class Store:
    def __init__(self, path="data/radar.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ escritura

    def upsert_many(self, listings: Iterable[Listing]) -> List[Change]:
        """Guarda los anuncios y devuelve los cambios dignos de notificacion.

        Un anuncio es "nuevo" la primera vez que lo vemos. Un cambio de precio
        se registra siempre que el precio difiera del ultimo conocido.
        """
        now = time.time()
        changes: List[Change] = []
        cur = self.db.cursor()

        for lst in listings:
            row = cur.execute(
                "SELECT price FROM listings WHERE key = ?", (lst.key,)).fetchone()

            if row is None:
                cur.execute(
                    """INSERT INTO listings
                       (key, source, source_id, url, title, price, rooms, baths, area,
                        municipality, province, ptype, occupied, occupied_reason,
                        description, agency, fingerprint, first_seen, last_seen, active, notified)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (lst.key, lst.source, lst.source_id, lst.url, lst.title, lst.price,
                     lst.rooms, lst.baths, lst.area, lst.municipality, lst.province,
                     lst.ptype, _bool(lst.occupied), lst.occupied_reason,
                     lst.description[:MAX_DESC], lst.agency, lst.fingerprint, now, now))
                cur.execute("INSERT OR REPLACE INTO price_history VALUES (?,?,?)",
                            (lst.key, now, lst.price))
                changes.append(Change(kind="nuevo", listing=lst, new_price=lst.price))
                continue

            old_price = row["price"]
            if lst.price is not None and old_price is not None and lst.price != old_price:
                cur.execute("INSERT OR REPLACE INTO price_history VALUES (?,?,?)",
                            (lst.key, now, lst.price))
                changes.append(Change(kind="precio", listing=lst,
                                      old_price=old_price, new_price=lst.price))

            # COALESCE en `occupied`: la tarjeta del listado casi nunca dice nada
            # sobre la ocupacion, asi que sin esto un barrido posterior borraria
            # lo que ya se habia confirmado abriendo la ficha completa. Un dato
            # desconocido no debe pisar nunca uno conocido.
            cur.execute(
                """UPDATE listings SET url=?, title=?, price=?, rooms=?, baths=?, area=?,
                       municipality=?, province=?, ptype=?,
                       occupied = COALESCE(?, occupied),
                       occupied_reason = CASE WHEN ? IS NULL THEN occupied_reason ELSE ? END,
                       description=?, agency=?, fingerprint=?, last_seen=?, active=1
                   WHERE key=?""",
                (lst.url, lst.title, lst.price, lst.rooms, lst.baths, lst.area,
                 lst.municipality, lst.province, lst.ptype,
                 _bool(lst.occupied), _bool(lst.occupied), lst.occupied_reason,
                 lst.description[:MAX_DESC], lst.agency,
                 lst.fingerprint, now, lst.key))

        self.db.commit()
        return changes

    def mark_inactive(self, source: str, seen_keys: set, province: Optional[str] = None):
        """Marca como retirados los anuncios de una fuente que ya no aparecen.

        Solo debe llamarse tras un barrido COMPLETO: en un barrido rapido la
        ausencia de un anuncio no significa nada.
        """
        q = "SELECT key FROM listings WHERE source = ? AND active = 1"
        params: list = [source]
        if province:
            q += " AND province = ?"
            params.append(province)
        gone = [r["key"] for r in self.db.execute(q, params) if r["key"] not in seen_keys]
        if gone:
            self.db.executemany("UPDATE listings SET active = 0 WHERE key = ?",
                                [(k,) for k in gone])
            self.db.commit()
        return gone

    def mark_notified(self, keys: Iterable[str]) -> None:
        self.db.executemany("UPDATE listings SET notified = 1 WHERE key = ?",
                            [(k,) for k in keys])
        self.db.commit()

    def log_run(self, mode, source, seen, matched, nuevos, cambios, error="") -> None:
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?)",
                        (time.time(), mode, source, seen, matched, nuevos, cambios, error))
        self.db.commit()

    # ------------------------------------------------------------------ lectura

    def compactar(self) -> None:
        """Recorta descripciones antiguas y compacta el fichero.

        SQLite no devuelve al sistema el espacio que libera, asi que sin el
        VACUUM el fichero se queda con el tamano de su peor momento.
        """
        self.db.execute(
            "UPDATE listings SET description = SUBSTR(description, 1, ?) "
            "WHERE LENGTH(description) > ?", (MAX_DESC, MAX_DESC))
        self.db.commit()
        self.db.execute("VACUUM")
        self.db.commit()

    def get_meta(self, clave: str, defecto=None):
        r = self.db.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
        return r["valor"] if r else defecto

    def set_meta(self, clave: str, valor) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (clave, str(valor)))
        self.db.commit()

    def is_first_run(self) -> bool:
        return self.db.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"] == 0

    def active_listings(self, incluir_ocupados: bool = False):
        """Anuncios vigentes. Los confirmados como ocupados quedan fuera."""
        q = "SELECT * FROM listings WHERE active = 1"
        if not incluir_ocupados:
            q += " AND (occupied IS NULL OR occupied = 0)"
        return list(self.db.execute(q + " ORDER BY price ASC"))

    def price_history(self, key: str):
        return list(self.db.execute(
            "SELECT ts, price FROM price_history WHERE key = ? ORDER BY ts", (key,)))

    def stats(self) -> dict:
        c = self.db.execute(
            """SELECT COUNT(*) total,
                      SUM(active) activos,
                      SUM(CASE WHEN occupied = 1 THEN 1 ELSE 0 END) ocupados,
                      SUM(CASE WHEN active = 1 AND (occupied IS NULL OR occupied = 0)
                               THEN 1 ELSE 0 END) coinciden
               FROM listings""").fetchone()
        return {"total": c["total"], "activos": c["activos"] or 0,
                "ocupados": c["ocupados"] or 0, "coinciden": c["coinciden"] or 0}


def _bool(v):
    return None if v is None else int(v)
