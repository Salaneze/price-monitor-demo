"""Хранилище снимков и поиск изменений.

Ключ товара — артикул (UPC). Повторный обход обновляет строку, а не добавляет
новую: в таблице всегда одна строка на товар плюс история цен отдельно.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .scraper import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    upc        TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    category   TEXT NOT NULL,
    price      TEXT NOT NULL,   -- Decimal строкой: float на деньгах даёт 51.769999
    qty        INTEGER NOT NULL,
    rating     INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS history (
    upc   TEXT NOT NULL,
    ts    TEXT NOT NULL,
    price TEXT NOT NULL,
    qty   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS history_upc ON history (upc, ts);
"""


@dataclass
class Change:
    kind: str          # new | cheaper | pricier | out | back | gone
    upc: str
    title: str
    url: str
    old_price: Decimal | None = None
    new_price: Decimal | None = None


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def apply_snapshot(
    db: sqlite3.Connection,
    products: list[Product],
    failed_urls: list[str] = (),
    now: datetime | None = None,
) -> list[Change]:
    ts = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    old = {r["upc"]: r for r in db.execute("SELECT * FROM products")}
    first_run = not old
    changes: list[Change] = []

    for p in products:
        prev = old.get(p.upc)
        if prev is None:
            # На первом запуске новым является всё — 40 сообщений «новинка» никому не нужны
            if not first_run:
                changes.append(Change("new", p.upc, p.title, p.url, None, p.price))
        else:
            old_price = Decimal(prev["price"])
            if p.price < old_price:
                changes.append(Change("cheaper", p.upc, p.title, p.url, old_price, p.price))
            elif p.price > old_price:
                changes.append(Change("pricier", p.upc, p.title, p.url, old_price, p.price))
            if prev["qty"] > 0 and p.qty == 0:
                changes.append(Change("out", p.upc, p.title, p.url))
            elif (prev["qty"] == 0 or not prev["active"]) and p.qty > 0:
                changes.append(Change("back", p.upc, p.title, p.url))

        db.execute(
            """INSERT INTO products (upc, title, url, category, price, qty, rating, first_seen, last_seen, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(upc) DO UPDATE SET
                 title=excluded.title, url=excluded.url, category=excluded.category,
                 price=excluded.price, qty=excluded.qty, rating=excluded.rating,
                 last_seen=excluded.last_seen, active=1""",
            (p.upc, p.title, p.url, p.category, str(p.price), p.qty, p.rating, ts, ts),
        )
        if prev is None or Decimal(prev["price"]) != p.price or prev["qty"] != p.qty:
            db.execute("INSERT INTO history VALUES (?, ?, ?, ?)", (p.upc, ts, str(p.price), p.qty))

    # Пропавшим считаем только товар из тех же категорий, что обошли сейчас,
    # и только если его страница не упала по сети. Иначе сменил CATEGORIES
    # или словил таймаут — и получил «снято с продажи» на половину каталога.
    seen = {p.upc for p in products}
    scanned_cats = {p.category for p in products}
    failed = set(failed_urls)
    for upc, prev in old.items():
        if (prev["active"] and upc not in seen
                and prev["category"] in scanned_cats and prev["url"] not in failed):
            changes.append(Change("gone", upc, prev["title"], prev["url"]))
            db.execute("UPDATE products SET active=0 WHERE upc=?", (upc,))

    db.commit()
    return changes
