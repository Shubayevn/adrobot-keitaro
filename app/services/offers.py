"""Справочник офферов: кэш списка из Keitaro + поиск для автокомплита."""

import time
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import Offer

_cache: dict = {"at": 0.0, "items": []}
_lock = Lock()


def all_offers(kt: KeitaroClient, ttl: int | None = None, force: bool = False) -> list[dict]:
    ttl = kt.settings.offers_cache_ttl if ttl is None else ttl
    with _lock:
        fresh = time.monotonic() - _cache["at"] < ttl
        if force or not fresh or not _cache["items"]:
            items = kt.list_offers() or []
            _cache["items"] = [
                {"id": int(o["id"]), "name": o.get("name") or f"Offer #{o['id']}", "state": o.get("state")}
                for o in items
                if o.get("state", "active") != "deleted"
            ]
            _cache["at"] = time.monotonic()
        return list(_cache["items"])


def reset_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["items"] = []


def search(kt: KeitaroClient, q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip().lower()
    items = all_offers(kt)
    if not q:
        return items[:limit]
    exact = [o for o in items if str(o["id"]) == q]
    rest = [o for o in items if o not in exact and (q in o["name"].lower() or q in str(o["id"]))]
    return (exact + rest)[:limit]


def find(kt: KeitaroClient, offer_id: int) -> dict | None:
    for o in all_offers(kt):
        if o["id"] == offer_id:
            return o
    # мог появиться только что — перечитать
    for o in all_offers(kt, force=True):
        if o["id"] == offer_id:
            return o
    return None


def upsert_offer(db: Session, keitaro_id: int, name: str | None) -> Offer:
    offer = db.scalar(select(Offer).where(Offer.keitaro_id == keitaro_id))
    if offer is None:
        offer = Offer(keitaro_id=keitaro_id, name=name or f"Offer #{keitaro_id}")
        db.add(offer)
        db.flush()
    elif name and offer.name != name:
        offer.name = name
    return offer
