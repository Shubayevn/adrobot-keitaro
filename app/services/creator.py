"""«Создаватор» кампаний.

Кампания в Keitaro с двумя потоками:
  Flow 1 — ловит трафик из указанных стран и редиректит на гугл;
  Flow 2 — весь остальной трафик отправляет на выбранный оффер.
Плюс домен, группа и источник трафика.
Если поток создать не удалось — кампания удаляется (в архив Keitaro), полукампаний не остаётся.
"""

import re
import secrets
import string

from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient, KeitaroError
from app.services import editor
from app.services import offers as offers_svc

GEO_RE = re.compile(r"^[A-Z]{2}$")
_ALPHABET = string.ascii_letters + string.digits


class CreatorError(ValueError):
    pass


def parse_geo(raw: str | list[str]) -> list[str]:
    parts = raw if isinstance(raw, list) else re.split(r"[\s,;]+", raw or "")
    codes: list[str] = []
    for part in parts:
        code = part.strip().upper()
        if not code:
            continue
        if not GEO_RE.match(code):
            raise CreatorError(f"«{part}» — не двухбуквенный код страны (ISO 3166-1 alpha-2, например AU)")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise CreatorError("Укажите хотя бы одну страну")
    return codes


def make_alias(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def build_campaign_payload(name: str, domain_id: int, group_id: int, traffic_source_id: int) -> dict:
    return {
        "name": name,
        "alias": make_alias(),
        "type": "position",
        "state": "active",
        "domain_id": domain_id,
        "group_id": str(group_id),  # в спецификации group_id запроса — строка
        "traffic_source_id": traffic_source_id,
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
    }


def build_geo_stream(kt: KeitaroClient, campaign_id: int, geo: list[str]) -> dict:
    s = kt.settings
    return {
        "campaign_id": campaign_id,
        "name": f"Flow 1: {', '.join(geo)} -> google",
        "type": "regular",
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": s.redirect_action_type,
        "action_payload": s.redirect_url,
        "filters": [{"name": s.country_filter_name, "mode": "accept", "payload": geo}],
    }


def build_offer_stream(kt: KeitaroClient, campaign_id: int, offer_id: int) -> dict:
    s = kt.settings
    return {
        "campaign_id": campaign_id,
        "name": "Flow 2: offers",
        "type": "regular",
        "position": 2,
        "state": "active",
        "schema": s.offers_stream_schema,
        "action_type": s.offers_stream_action_type,
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


def create_campaign(
    db: Session,
    kt: KeitaroClient,
    *,
    name: str,
    geo: str | list[str],
    offer_id: int,
    domain_id: int | None,
    group_id: int | None,
    traffic_source_id: int | None,
    new_group_name: str | None = None,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise CreatorError("Укажите название кампании")
    codes = parse_geo(geo)

    s = kt.settings
    domain_id = domain_id or s.keitaro_default_domain_id
    traffic_source_id = traffic_source_id or s.keitaro_default_traffic_source_id
    new_group_name = (new_group_name or "").strip()
    group_id = group_id or s.keitaro_default_group_id
    missing = [
        label
        for label, value in (("домен", domain_id), ("группу", group_id or new_group_name), ("источник", traffic_source_id))
        if not value
    ]
    if missing:
        raise CreatorError("Выберите " + ", ".join(missing))

    if offers_svc.find(kt, offer_id) is None:
        raise CreatorError(f"Оффер #{offer_id} не найден в Keitaro")

    # группу создаём только после всех проверок, чтобы не плодить лишние
    if new_group_name:
        group_id = int(kt.create_group(new_group_name)["id"])

    campaign = kt.create_campaign(build_campaign_payload(name, domain_id, group_id, traffic_source_id))
    campaign_id = int(campaign["id"])
    try:
        kt.create_stream(build_geo_stream(kt, campaign_id, codes))
        kt.create_stream(build_offer_stream(kt, campaign_id, offer_id))
    except KeitaroError as exc:
        rollback = "кампания удалена"
        try:
            kt.delete_campaign(campaign_id)
        except KeitaroError:
            rollback = f"удалить кампанию #{campaign_id} не удалось — удалите её в Keitaro вручную"
        raise KeitaroError(f"Не удалось создать потоки ({exc}); {rollback}") from exc

    editor.fetch_campaign(db, kt, campaign_id)
    return {"id": campaign_id, "name": campaign.get("name", name), "alias": campaign.get("alias"), "geo": codes}
