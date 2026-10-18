"""Сбор товаров: страницы категорий -> карточки товаров.

Цену и наличие можно взять прямо со списка, но артикула (UPC) и точного
остатка там нет, поэтому за каждым товаром идём на его страницу. Это в N раз
больше запросов, зато ключ стабильный: ссылка у товара меняется при переносе
в другую категорию, артикул — нет.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


@dataclass
class Product:
    upc: str
    title: str
    url: str
    category: str
    price: Decimal
    qty: int
    rating: int


def parse_price(text: str) -> Decimal:
    # На сайте встречается «Â£51.77» — кривая перекодировка фунта; берём только цифры.
    m = re.search(r"\d+(?:[.,]\d+)?", text)
    if not m:
        raise ValueError(f"нет цены в {text!r}")
    return Decimal(m.group().replace(",", "."))


def parse_qty(text: str) -> int:
    # «In stock (19 available)» -> 19; «Out of stock» -> 0
    m = re.search(r"(\d+)\s+available", text)
    return int(m.group(1)) if m else 0


def parse_category_page(html: str, page_url: str) -> tuple[list[str], str | None]:
    """Ссылки на товары со страницы категории и адрес следующей страницы."""
    soup = BeautifulSoup(html, "lxml")
    links = [
        urljoin(page_url, a["href"])
        for a in soup.select("article.product_pod h3 a[href]")
    ]
    nxt = soup.select_one("ul.pager li.next a[href]")
    return links, urljoin(page_url, nxt["href"]) if nxt else None


def parse_product_page(html: str, url: str) -> Product:
    soup = BeautifulSoup(html, "lxml")
    table = {
        th.get_text(strip=True): td.get_text(strip=True)
        for th, td in (
            (row.th, row.td) for row in soup.select("table.table tr")
        )
        if th and td
    }
    crumbs = [li.get_text(strip=True) for li in soup.select("ul.breadcrumb li")]
    rating_el = soup.select_one("p.star-rating")
    rating_cls = next(
        (c for c in (rating_el.get("class", []) if rating_el else []) if c in RATINGS),
        None,
    )
    return Product(
        upc=table["UPC"],
        title=soup.select_one("div.product_main h1").get_text(strip=True),
        url=url,
        # Хлебные крошки: Home / Books / <категория> / <товар>
        category=crumbs[2] if len(crumbs) >= 4 else "",
        price=parse_price(table["Price (incl. tax)"]),
        qty=parse_qty(table.get("Availability", "")),
        rating=RATINGS.get(rating_cls, 0),
    )


async def _get(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        for attempt in range(3):
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                # 404 повтором не лечится, а 5xx и обрывы — часто да
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                    raise
                log.warning("повтор %s после %r", url, e)
                await asyncio.sleep(2 ** attempt)
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def collect(base_url: str, categories: list[str], concurrency: int) -> tuple[list[Product], list[str]]:
    """Возвращает товары и список адресов, которые не удалось разобрать.

    Сбой одной карточки не валит обход: товар просто не попадёт в этот снимок.
    Но и пропавшим его считать нельзя — поэтому адреса ошибок отдаём наружу,
    и сравнение со старым снимком их учитывает.
    """
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": "price-monitor-demo/1.0 (+github.com/Salaneze)"}
    starts = [urljoin(base_url, c) for c in categories] or [urljoin(base_url, "catalogue/page-1.html")]

    async with httpx.AsyncClient(headers=headers, timeout=20, follow_redirects=True) as client:
        product_urls: list[str] = []
        for page in starts:
            while page:
                links, page_next = parse_category_page(await _get(client, page, sem), page)
                product_urls += links
                page = page_next
        product_urls = list(dict.fromkeys(product_urls))
        log.info("товаров в списках: %d", len(product_urls))

        async def one(url: str) -> Product | None:
            try:
                return parse_product_page(await _get(client, url, sem), url)
            except Exception:
                log.exception("не разобрал %s", url)
                return None

        results = await asyncio.gather(*(one(u) for u in product_urls))

    failed = [u for u, p in zip(product_urls, results) if p is None]
    return [p for p in results if p], failed
