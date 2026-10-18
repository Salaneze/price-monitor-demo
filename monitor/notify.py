import logging

import httpx

from .store import Change

log = logging.getLogger(__name__)

LABELS = {
    "new": "🆕 Новинка",
    "cheaper": "📉 Подешевело",
    "pricier": "📈 Подорожало",
    "out": "⛔ Закончилось",
    "back": "✅ Снова в наличии",
    "gone": "🗑 Снято с продажи",
}
# Лимит Telegram на сообщение — 4096 символов; с запасом под разметку
CHUNK = 3500


def format_changes(changes: list[Change], currency: str = "£") -> list[str]:
    lines = []
    for c in changes:
        line = f"{LABELS[c.kind]}: {c.title}"
        if c.old_price is not None and c.new_price is not None:
            line += f" — {currency}{c.old_price} → {currency}{c.new_price}"
        elif c.new_price is not None:
            line += f" — {currency}{c.new_price}"
        lines.append(f"{line}\n{c.url}")

    messages, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 2 > CHUNK:
            messages.append(cur)
            cur = ""
        cur += line + "\n\n"
    if cur:
        messages.append(cur)
    return messages


def send_telegram(token: str, chat_id: str, changes: list[Change]) -> None:
    if not (token and chat_id and changes):
        return
    for text in format_changes(changes):
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        # Ошибку (неверный chat_id, бот заблокирован) Telegram присылает телом
        # с ok=false — исключения не будет, и без проверки она пройдёт молча
        if r.status_code != 200 or not r.json().get("ok"):
            log.error("Telegram не принял сообщение: %s", r.text[:300])
