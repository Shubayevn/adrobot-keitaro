from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.keitaro import KeitaroClient, get_keitaro
from app.schemas import AddOfferIn, CreateCampaignIn, PinIn, ShareIn, campaign_out, stream_out
from app.services import creator, editor
from app.services import offers as offers_svc

router = APIRouter(prefix="/api")


# ---------- справочники ----------

@router.get("/offers")
def search_offers(q: str = "", kt: KeitaroClient = Depends(get_keitaro)):
    return offers_svc.search(kt, q)


@router.get("/lookups")
def lookups(kt: KeitaroClient = Depends(get_keitaro)):
    s = kt.settings

    def short(items, label="name"):
        return [{"id": int(i["id"]), "name": i.get(label) or f"#{i['id']}"} for i in items or []
                if i.get("state", "active") != "deleted"]

    return {
        "domains": short(kt.list_domains()),
        "groups": short(kt.list_groups("campaigns")),
        "traffic_sources": short(kt.list_traffic_sources()),
        "defaults": {
            "domain_id": s.keitaro_default_domain_id,
            "group_id": s.keitaro_default_group_id,
            "traffic_source_id": s.keitaro_default_traffic_source_id,
        },
    }


# ---------- кампании ----------

@router.get("/campaigns")
def list_campaigns(kt: KeitaroClient = Depends(get_keitaro)):
    return [
        {"id": int(c["id"]), "name": c.get("name"), "alias": c.get("alias"), "state": c.get("state")}
        for c in kt.list_campaigns() or []
        if c.get("state") != "deleted"
    ]


@router.post("/campaigns", status_code=201)
def create_campaign(body: CreateCampaignIn, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    return creator.create_campaign(db, kt, **body.model_dump())


@router.get("/campaigns/{keitaro_id}")
def campaign_state(keitaro_id: int, db: Session = Depends(get_db)):
    campaign = editor.get_campaign(db, keitaro_id)
    if campaign is None:
        return {"keitaro_id": keitaro_id, "name": None, "fetched_at": None, "streams": []}
    return campaign_out(campaign)


@router.post("/campaigns/{keitaro_id}/fetch")
def fetch_streams(keitaro_id: int, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    return campaign_out(editor.fetch_campaign(db, kt, keitaro_id))


# ---------- поток ----------

@router.post("/streams/{stream_id}/offers")
def add_offer(stream_id: int, body: AddOfferIn, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    return stream_out(editor.add_offer(db, kt, stream_id, body.offer_id))


@router.post("/streams/{stream_id}/cancel")
def cancel(stream_id: int, db: Session = Depends(get_db)):
    return stream_out(editor.cancel(db, stream_id))


@router.post("/streams/{stream_id}/push")
def push(stream_id: int, db: Session = Depends(get_db), kt: KeitaroClient = Depends(get_keitaro)):
    return stream_out(editor.push(db, kt, stream_id))


@router.post("/stream-offers/{link_id}/remove")
def remove(link_id: int, db: Session = Depends(get_db)):
    return stream_out(editor.remove_offer(db, link_id))


@router.post("/stream-offers/{link_id}/bring-back")
def bring_back(link_id: int, db: Session = Depends(get_db)):
    return stream_out(editor.bring_back(db, link_id))


@router.post("/stream-offers/{link_id}/pin")
def pin(link_id: int, body: PinIn, db: Session = Depends(get_db)):
    return stream_out(editor.set_pin(db, link_id, body.pinned))


@router.post("/stream-offers/{link_id}/share")
def share(link_id: int, body: ShareIn, db: Session = Depends(get_db)):
    return stream_out(editor.set_share(db, link_id, body.share))
