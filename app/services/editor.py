"""Редактор офферов в потоках кампании (логика из видео).

- fetch: забрать потоки из Keitaro. Офферы, о которых мы знали, но которых больше нет
  в Keitaro, не удаляются, а уходят в removed (серые, 0%, есть «Bring back»).
  Неопубликованный черновик при этом сбрасывается — Keitaro считается источником правды.
- add / remove / bring back / pin / share: меняют только черновик и пересчитывают веса,
  поток становится «жёлтым» (есть неопубликованные изменения).
- cancel: новые привязки удаляются, остальные откатываются к опубликованному состоянию.
- push: активные офферы с долями уходят в Keitaro, затем поток перечитывается и сверяется.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient, KeitaroError
from app.models import ACTIVE, REMOVED, Campaign, Stream, StreamOffer
from app.services import offers as offers_svc
from app.services.weights import TOTAL, WeightError, pinned_sum, recalculate, validate_for_publish


class EditorError(ValueError):
    pass


# ---------- чтение ----------

def get_campaign(db: Session, keitaro_campaign_id: int) -> Campaign | None:
    return db.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_campaign_id))


def get_stream(db: Session, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise EditorError("Поток не найден")
    return stream


def get_link(db: Session, link_id: int) -> StreamOffer:
    link = db.get(StreamOffer, link_id)
    if link is None:
        raise EditorError("Оффер в потоке не найден")
    return link


def stream_is_dirty(stream: Stream) -> bool:
    return any(link.is_dirty for link in stream.offers)


# ---------- fetch из Keitaro ----------

def _kt_offer_links(kt_stream: dict) -> list[dict]:
    return [o for o in (kt_stream.get("offers") or []) if o.get("state", ACTIVE) == ACTIVE]


def fetch_campaign(db: Session, kt: KeitaroClient, keitaro_campaign_id: int) -> Campaign:
    kt_campaign = kt.get_campaign(keitaro_campaign_id)
    kt_streams = kt.list_streams(keitaro_campaign_id) or []
    names = {o["id"]: o["name"] for o in offers_svc.all_offers(kt, force=True)}

    campaign = get_campaign(db, keitaro_campaign_id)
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_campaign_id, name=kt_campaign.get("name") or "")
        db.add(campaign)
    campaign.name = kt_campaign.get("name") or campaign.name
    campaign.alias = kt_campaign.get("alias")
    campaign.fetched_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()

    by_kid = {s.keitaro_id: s for s in campaign.streams}
    seen: set[int] = set()
    for kt_stream in kt_streams:
        if kt_stream.get("state") == "deleted":
            continue
        kid = int(kt_stream["id"])
        seen.add(kid)
        stream = by_kid.get(kid)
        if stream is None:
            stream = db.scalar(select(Stream).where(Stream.keitaro_id == kid))
        if stream is None:
            stream = Stream(keitaro_id=kid, campaign=campaign, name="")
            db.add(stream)
        stream.campaign = campaign
        stream.name = kt_stream.get("name") or f"Stream #{kid}"
        stream.position = int(kt_stream.get("position") or 0)
        stream.type = kt_stream.get("type")
        stream.schema = kt_stream.get("schema")
        db.flush()
        _sync_stream_offers(db, stream, _kt_offer_links(kt_stream), names)

    for stream in list(campaign.streams):
        if stream.keitaro_id not in seen:
            campaign.streams.remove(stream)

    db.commit()
    db.refresh(campaign)
    return campaign


def _sync_stream_offers(db: Session, stream: Stream, kt_links: list[dict], names: dict[int, str]) -> None:
    local = {link.offer.keitaro_id: link for link in stream.offers}
    kt_ids: set[int] = set()

    for kt_link in kt_links:
        oid = int(kt_link["offer_id"])
        kt_ids.add(oid)
        share = int(kt_link.get("share") or 0)
        link = local.get(oid)
        if link is None:
            offer = offers_svc.upsert_offer(db, oid, names.get(oid))
            link = StreamOffer(stream=stream, offer=offer, pinned=False, published_pinned=False)
            db.add(link)
            local[oid] = link
        elif oid in names:
            link.offer.name = names[oid]
        link.status = ACTIVE
        link.share = share
        link.is_new = False
        link.published_status = ACTIVE
        link.published_share = share
        # pin — локальная настройка, Keitaro о ней не знает: оставляем опубликованную
        link.pinned = link.published_pinned

    for oid, link in local.items():
        if oid in kt_ids:
            continue
        if link.is_new:  # так и не был опубликован, а черновик сбрасываем
            stream.offers.remove(link)
            continue
        link.status = REMOVED
        link.share = 0
        link.pinned = False
        link.published_status = REMOVED
        link.published_share = 0
        link.published_pinned = False

    stream.has_offers = bool(kt_ids) or any(link.status == REMOVED for link in stream.offers)
    db.flush()


# ---------- правки черновика ----------

def _back_to_published(stream: Stream) -> bool:
    """Набор офферов и закреплений совпал с опубликованным (например, добавили и тут же убрали)."""
    return all(
        not link.is_new and link.status == link.published_status and link.pinned == link.published_pinned
        for link in stream.offers
    )


def _recalc(stream: Stream, allow_restore: bool = True) -> None:
    if allow_restore and _back_to_published(stream):
        # Возвращаем ровно опубликованные доли: иначе 33/33/34 из Keitaro
        # «пересчиталось» бы в 34/33/33 и поток зря стал бы жёлтым.
        for link in stream.offers:
            link.share = link.published_share
        return
    try:
        recalculate(stream.offers)
    except WeightError as exc:
        raise EditorError(str(exc)) from exc


def add_offer(db: Session, kt: KeitaroClient, stream_id: int, offer_keitaro_id: int) -> Stream:
    stream = get_stream(db, stream_id)
    if not stream.has_offers:
        raise EditorError("В этом потоке нет офферов — его содержимое обёртка не редактирует")
    kt_offer = offers_svc.find(kt, offer_keitaro_id)
    if kt_offer is None:
        raise EditorError(f"Оффер #{offer_keitaro_id} не найден в Keitaro")

    existing = next((link for link in stream.offers if link.offer.keitaro_id == offer_keitaro_id), None)
    if existing is not None:
        if existing.status == ACTIVE:
            raise EditorError("Этот оффер уже есть в потоке")
        existing.status = ACTIVE  # был удалён — возвращаем
        existing.pinned = False
    else:
        offer = offers_svc.upsert_offer(db, offer_keitaro_id, kt_offer["name"])
        link = StreamOffer(
            stream=stream,
            offer=offer,
            status=ACTIVE,
            share=0,
            pinned=False,
            is_new=True,
            published_status=REMOVED,
            published_share=0,
            published_pinned=False,
        )
        db.add(link)
        db.flush()
        db.refresh(stream)
    _recalc(stream)
    db.commit()
    return stream


def remove_offer(db: Session, link_id: int) -> Stream:
    link = get_link(db, link_id)
    stream = link.stream
    if link.status == REMOVED:
        raise EditorError("Оффер уже удалён")
    if link.is_new:
        # в Keitaro его ещё нет — просто убираем привязку
        stream.offers.remove(link)
    else:
        link.status = REMOVED
    _recalc(stream)
    db.commit()
    return stream


def bring_back(db: Session, link_id: int) -> Stream:
    link = get_link(db, link_id)
    if link.status != REMOVED:
        raise EditorError("Оффер не удалён")
    link.status = ACTIVE
    link.pinned = False
    _recalc(link.stream)
    db.commit()
    return link.stream


def set_pin(db: Session, link_id: int, pinned: bool) -> Stream:
    link = get_link(db, link_id)
    if link.status != ACTIVE:
        raise EditorError("Закрепить можно только активный оффер")
    link.pinned = pinned
    _recalc(link.stream)
    db.commit()
    return link.stream


def set_share(db: Session, link_id: int, share: int) -> Stream:
    """Ручная доля = доля закрепляется, остальные пересчитываются."""
    link = get_link(db, link_id)
    if link.status != ACTIVE:
        raise EditorError("Долю можно задать только активному офферу")
    if not 0 <= share <= TOTAL:
        raise EditorError("Доля должна быть от 0 до 100")
    others = [lnk for lnk in link.stream.offers if lnk is not link]
    if pinned_sum(others) + share > TOTAL:
        raise EditorError(
            f"Сумма закреплённых долей превысит 100% (уже закреплено {pinned_sum(others)}%)"
        )
    link.share = share
    link.pinned = True
    _recalc(link.stream, allow_restore=False)
    db.commit()
    return link.stream


def cancel(db: Session, stream_id: int) -> Stream:
    stream = get_stream(db, stream_id)
    for link in list(stream.offers):
        if link.is_new:
            stream.offers.remove(link)
            continue
        link.status = link.published_status
        link.share = link.published_share
        link.pinned = link.published_pinned
    db.commit()
    db.refresh(stream)
    return stream


# ---------- push в Keitaro ----------

def push(db: Session, kt: KeitaroClient, stream_id: int) -> Stream:
    stream = get_stream(db, stream_id)
    try:
        validate_for_publish(stream.offers)
    except WeightError as exc:
        raise EditorError(str(exc)) from exc

    active = [link for link in stream.offers if link.status == ACTIVE]
    payload = {
        "offers": [
            {"offer_id": link.offer.keitaro_id, "share": link.share, "state": ACTIVE} for link in active
        ]
    }
    kt.update_stream(stream.keitaro_id, payload)

    # Сверяем, что Keitaro сохранил ровно то, что отправили
    saved = {int(o["offer_id"]): int(o.get("share") or 0) for o in _kt_offer_links(kt.get_stream(stream.keitaro_id))}
    expected = {o["offer_id"]: o["share"] for o in payload["offers"]}
    if saved != expected:
        raise KeitaroError(
            f"Keitaro сохранил другой набор офферов: отправили {expected}, в трекере {saved}. "
            "Нажмите «Fetch streams», чтобы увидеть актуальное состояние."
        )

    for link in list(stream.offers):
        if link.status == REMOVED and link.is_new:
            stream.offers.remove(link)
            continue
        link.is_new = False
        link.published_status = link.status
        link.published_share = link.share
        link.published_pinned = link.pinned
    db.commit()
    db.refresh(stream)
    return stream
