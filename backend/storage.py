"""Tarjetas guardadas en el Mint, en la carpeta data/ que Git y Docker ignoran."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CARDS_DIR = Path("/data/cards")
CARD_ID = re.compile(r"^[A-Za-z0-9-]+$")


class NameTaken(Exception):
    """El nombre ya lo usa otra tarjeta guardada."""


def _normalise(name: str) -> str:
    return " ".join(name.split()).casefold()


def name_taken(name: str, exclude_id: str | None = None) -> bool:
    target = _normalise(name)
    for path in CARDS_DIR.glob("*.json"):
        if exclude_id and path.stem == exclude_id:
            continue
        try:
            if _normalise(json.loads(path.read_text())["name"]) == target:
                return True
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return False


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _summary(card_id: str, card: dict) -> dict:
    return {
        "id": card_id,
        "name": card["name"],
        "uid": card["uid"],
        "type": card["type"],
        "read_at": card["read_at"],
        "sectors_read": sum(1 for sector in card["sectors"] if sector["key"]),
        "sectors_total": len(card["sectors"]),
    }


def save_card(name: str, reading: dict) -> dict:
    CARDS_DIR.mkdir(mode=0o700, exist_ok=True)
    if name_taken(name):
        raise NameTaken(name)
    uid = (reading["uid"] or "sin-uid").replace(" ", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    card_id = "-".join(part for part in (timestamp, uid, _slug(name)) if part)
    path = CARDS_DIR / f"{card_id}.json"
    if path.exists():
        raise FileExistsError(card_id)

    card = {"name": name, **reading}
    temporary = path.with_suffix(".tmp")
    # La tarjeta incluye las claves que han funcionado: solo la puede leer su dueño
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(card, file, indent=2, ensure_ascii=False)
    os.replace(temporary, path)
    return _summary(card_id, card)


def list_cards() -> list[dict]:
    cards = []
    for path in CARDS_DIR.glob("*.json"):
        try:
            cards.append(_summary(path.stem, json.loads(path.read_text())))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return sorted(cards, key=lambda card: card["read_at"], reverse=True)


def load_card(card_id: str) -> dict | None:
    if not CARD_ID.match(card_id):
        return None
    path = CARDS_DIR / f"{card_id}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def rename_card(card_id: str, new_name: str) -> dict | None:
    if not CARD_ID.match(card_id):
        return None
    path = CARDS_DIR / f"{card_id}.json"
    if not path.is_file():
        return None
    if name_taken(new_name, exclude_id=card_id):
        raise NameTaken(new_name)
    card = json.loads(path.read_text())
    card["name"] = new_name
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(card, file, indent=2, ensure_ascii=False)
    os.replace(temporary, path)
    return _summary(card_id, card)
