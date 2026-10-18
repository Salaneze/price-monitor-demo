"""python -m monitor            один обход
python -m monitor --every 6h  обход каждые 6 часов, пока не остановят
"""
import argparse
import asyncio
import logging
import re
import sys
import time

from . import export, notify, store
from .config import settings
from .scraper import collect

log = logging.getLogger("monitor")


def parse_interval(text: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([mhd])", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("формат: 30m, 6h, 1d")
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]


def run_once() -> int:
    started = time.monotonic()
    products, failed = asyncio.run(collect(settings.base_url, settings.categories, settings.concurrency))
    db = store.connect(settings.db_path)
    try:
        changes = store.apply_snapshot(db, products, failed)
        export.to_xlsx(db, settings.xlsx_path)
        if settings.gsheet_id and settings.gsheet_credentials:
            export.to_gsheet(db, settings.gsheet_id, settings.gsheet_credentials)
    finally:
        db.close()

    notify.send_telegram(settings.tg_token, settings.tg_chat_id, changes)
    log.info("товаров %d, изменений %d, ошибок %d, %.1f с",
             len(products), len(changes), len(failed), time.monotonic() - started)
    for c in changes:
        log.info("  %s: %s", c.kind, c.title)
    return 1 if failed and not products else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # Консоль Windows по умолчанию cp1251 — на названиях с «é» вывод падал
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    # httpx на INFO пишет строку на каждый запрос — тысяча строк заслоняет итог
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ap = argparse.ArgumentParser(prog="python -m monitor")
    ap.add_argument("--every", type=parse_interval, help="повторять обход: 30m, 6h, 1d")
    args = ap.parse_args()

    if not args.every:
        return run_once()
    while True:
        try:
            run_once()
        except Exception:
            # Сайт лёг на час — это не повод останавливать мониторинг на неделю
            log.exception("обход упал, следующий по расписанию")
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
