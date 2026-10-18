import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("BASE_URL", "https://books.toscrape.com/")
    # Пути категорий относительно BASE_URL. Пусто — весь каталог (1000 товаров,
    # ~1100 запросов, пара минут при CONCURRENCY=5).
    categories: list[str] = field(default_factory=lambda: _list(
        "CATEGORIES",
        "catalogue/category/books/travel_2/,catalogue/category/books/mystery_3/",
    ))
    # Больше 5 параллельных запросов к чужому сайту — уже не мониторинг, а нагрузка.
    concurrency: int = int(os.getenv("CONCURRENCY", "5"))
    db_path: Path = Path(os.getenv("DB_PATH", "data/monitor.db"))
    xlsx_path: Path = Path(os.getenv("XLSX_PATH", "data/prices.xlsx"))

    tg_token: str = os.getenv("TG_TOKEN", "")
    tg_chat_id: str = os.getenv("TG_CHAT_ID", "")

    gsheet_id: str = os.getenv("GSHEET_ID", "")
    gsheet_credentials: str = os.getenv("GSHEET_CREDENTIALS", "")


settings = Settings()
