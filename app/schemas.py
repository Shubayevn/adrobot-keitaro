from pydantic import BaseModel, Field

from app.models import Campaign, Stream


class CreateCampaignIn(BaseModel):
    name: str
    geo: str = Field(description="Коды стран через запятую: AU, MX")
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None
    new_group_name: str | None = None


class AddOfferIn(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    pinned: bool


class ShareIn(BaseModel):
    share: int


def stream_out(stream: Stream) -> dict:
    links = sorted(stream.offers, key=lambda link: link.id)
    return {
        "id": stream.id,
        "keitaro_id": stream.keitaro_id,
        "name": stream.name,
        "position": stream.position,
        "type": stream.type,
        "schema": stream.schema,
        "has_offers": stream.has_offers,
        "dirty": any(link.is_dirty for link in links),
        "total_share": sum(link.share for link in links if link.status == "active"),
        "offers": [
            {
                "id": link.id,
                "offer_id": link.offer.keitaro_id,
                "name": link.offer.name,
                "status": link.status,
                "share": link.share,
                "pinned": link.pinned,
                "is_new": link.is_new,
                "dirty": link.is_dirty,
                "published_status": link.published_status,
                "published_share": link.published_share,
            }
            for link in links
        ],
    }


def campaign_out(campaign: Campaign) -> dict:
    return {
        "id": campaign.id,
        "keitaro_id": campaign.keitaro_id,
        "name": campaign.name,
        "alias": campaign.alias,
        "fetched_at": campaign.fetched_at.isoformat() if campaign.fetched_at else None,
        "streams": [stream_out(s) for s in sorted(campaign.streams, key=lambda s: (s.position, s.id))],
    }
