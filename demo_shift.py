"""Сдвигает сохранённый снимок, чтобы следующий обход нашёл изменения.

Учебный сайт books.toscrape.com цены не меняет никогда, поэтому без этого
скрипта уведомления в демо не увидеть. Делает вид, что при прошлом обходе
три книги стоили дороже, а одна была распродана:

    python -m monitor        # первый обход, снимок
    python demo_shift.py     # «откатить» снимок
    python -m monitor        # 3 × «Подешевело», 1 × «Снова в наличии»

На реальном сайте не нужен — там цены меняются сами.
"""
import sqlite3
import sys
from decimal import Decimal

from monitor.config import settings


def main() -> int:
    if not settings.db_path.exists():
        print("Снимка ещё нет — сначала python -m monitor")
        return 1
    db = sqlite3.connect(settings.db_path)
    rows = db.execute("SELECT upc, title, price FROM products WHERE active=1 AND qty>0 ORDER BY upc LIMIT 4").fetchall()
    if len(rows) < 4:
        print("В снимке меньше 4 товаров в наличии")
        return 1
    for upc, title, price in rows[:3]:
        old = (Decimal(price) * Decimal("1.15")).quantize(Decimal("0.01"))
        db.execute("UPDATE products SET price=? WHERE upc=?", (str(old), upc))
        print(f"{title}: было бы £{old}, сейчас £{price}")
    upc, title, _ = rows[3]
    db.execute("UPDATE products SET qty=0 WHERE upc=?", (upc,))
    print(f"{title}: отмечен распроданным")
    db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
