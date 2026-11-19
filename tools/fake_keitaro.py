"""Фейковый Keitaro Admin API v1 в памяти — для тестов и демо без настоящего трекера.

Запуск:  uv run uvicorn tools.fake_keitaro:app --port 8081
Покрывает только эндпоинты, которые использует обёртка. Поведение PUT /streams/{id}
с полем offers — замена списка целиком (так обёртка ожидает от настоящего Keitaro).
"""

import copy
import itertools

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

SEED_OFFERS = [
    (3749, "Miaflow [BEAUTY-RO-BE_0009] [pl - - spin ro -] 2. Основной, Румыния JS"),
    (3717, "Miaflow [BEAUTY-RO-BE_0008] [pl - - prize ro -] 1. Основной, Румыния JS"),
    (3801, "11111 FitoMishki [Weight Loss-CO-DT_0309] [pl es -]"),
    (3802, "11112 Oxys [BEAUTY-CL-BE_0155] [pl es -]"),
    (3803, "Cardio Plus [HEALTH-MX-HE_0042] [pl es -]"),
    (3804, "Slim Fit [Weight Loss-RO-DT_0101] [pl ro -]"),
    (3805, "Joint Pro [HEALTH-AU-HE_0007] [pl en -]"),
]


class FakeKeitaro:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self._ids = itertools.count(1000)
        self.domains = [{"id": 1, "name": "https://in.posdk.xyz/", "state": "active"},
                        {"id": 2, "name": "https://go.example.org/", "state": "active"}]
        self.groups = [{"id": 1, "name": "FORTESTS", "type": "campaigns"},
                       {"id": 2, "name": "RO", "type": "campaigns"}]
        self.sources = [{"id": 1, "name": "FORTESTS", "state": "active"},
                        {"id": 2, "name": "Facebook", "state": "active"}]
        self.offers = [{"id": i, "name": n, "state": "active"} for i, n in SEED_OFFERS]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self.calls: list[tuple[str, str, object]] = []
        # кампания как в видео: Flow 1 (AU -> google), Flow 2 с тремя офферами 33/33/34
        c = self._add_campaign({"name": "campaign 2", "alias": "wVqN1R", "domain_id": 1,
                                "group_id": "1", "traffic_source_id": 1, "type": "position"})
        self._add_stream({"campaign_id": c["id"], "name": "Flow 1", "type": "regular", "position": 1,
                          "schema": "redirect", "action_type": "http", "action_payload": "https://google.com",
                          "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}]})
        self._add_stream({"campaign_id": c["id"], "name": "Flow 2", "type": "regular", "position": 2,
                          "schema": "landings", "action_type": "http",
                          "offers": [{"offer_id": 3749, "share": 33, "state": "active"},
                                     {"offer_id": 3717, "share": 33, "state": "active"},
                                     {"offer_id": 3801, "share": 34, "state": "active"}]})

    # --- helpers ---
    def _add_campaign(self, data: dict) -> dict:
        cid = next(self._ids)
        c = {"id": cid, "state": "active", "type": "position", **data}
        self.campaigns[cid] = c
        return c

    def _offer_links(self, sid: int, offers: list[dict]) -> list[dict]:
        return [{"id": next(self._ids), "stream_id": sid, "offer_id": int(o["offer_id"]),
                 "share": int(o["share"]), "state": o.get("state", "active")} for o in offers]

    def _add_stream(self, data: dict) -> dict:
        sid = next(self._ids)
        s = {"id": sid, "state": "active", "filters": [], "landings": [], "offers": [], **data}
        s["offers"] = self._offer_links(sid, data.get("offers", []))
        self.streams[sid] = s
        return s


def create_app(api_key: str | None = None, fake: FakeKeitaro | None = None) -> FastAPI:
    kt = fake or FakeKeitaro(api_key)
    app = FastAPI(title="Fake Keitaro Admin API")
    app.state.kt = kt

    def auth(key: str | None):
        if kt.api_key and key != kt.api_key:
            raise HTTPException(401, detail={"error": "Unauthorized"})

    def nf(what: str):
        raise HTTPException(404, detail={"error": f"{what} not found"})

    @app.middleware("http")
    async def log_calls(request: Request, call_next):
        body = await request.body()
        kt.calls.append((request.method, request.url.path, body.decode() if body else None))
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def keitaro_error_format(_: Request, exc: HTTPException):
        # Keitaro отвечает {"error": "..."} без обёртки detail
        body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=body)

    p = "/admin_api/v1"

    @app.get(p + "/offers")
    def offers(api_key: str | None = Header(None)):
        auth(api_key)
        return kt.offers

    @app.get(p + "/domains")
    def domains(api_key: str | None = Header(None)):
        auth(api_key)
        return kt.domains

    @app.get(p + "/groups")
    def groups(type: str = "campaigns", api_key: str | None = Header(None)):
        auth(api_key)
        return [g for g in kt.groups if g["type"] == type]

    @app.post(p + "/groups")
    def create_group(data: dict, api_key: str | None = Header(None)):
        auth(api_key)
        if not data.get("name"):
            raise HTTPException(406, detail={"name": ["required"]})
        g = {"id": next(kt._ids), "name": data["name"], "type": data.get("type", "campaigns")}
        kt.groups.append(g)
        return g

    @app.get(p + "/traffic_sources")
    def sources(api_key: str | None = Header(None)):
        auth(api_key)
        return kt.sources

    @app.get(p + "/stream_filters")
    def stream_filters(api_key: str | None = Header(None)):
        auth(api_key)
        return [{"value": "country", "tooltip": "Country", "modes": {"accept": "accept", "reject": "reject"}}]

    @app.get(p + "/streams_actions")
    def stream_actions(api_key: str | None = Header(None)):
        auth(api_key)
        return [{"key": "http", "name": "HTTP redirect", "type": "redirect"}]

    @app.get(p + "/campaigns")
    def campaigns(api_key: str | None = Header(None)):
        auth(api_key)
        return list(kt.campaigns.values())

    @app.get(p + "/campaigns/{cid}")
    def campaign(cid: int, api_key: str | None = Header(None)):
        auth(api_key)
        return kt.campaigns.get(cid) or nf("Campaign")

    @app.post(p + "/campaigns")
    def create_campaign(data: dict, api_key: str | None = Header(None)):
        auth(api_key)
        for f in ("name", "alias"):
            if not data.get(f):
                raise HTTPException(406, detail={f: ["required"]})
        return kt._add_campaign(data)

    @app.delete(p + "/campaigns/{cid}")
    def delete_campaign(cid: int, api_key: str | None = Header(None)):
        auth(api_key)
        c = kt.campaigns.get(cid) or nf("Campaign")
        c["state"] = "deleted"
        return c

    @app.get(p + "/campaigns/{cid}/streams")
    def campaign_streams(cid: int, api_key: str | None = Header(None)):
        auth(api_key)
        if cid not in kt.campaigns:
            nf("Campaign")
        return sorted([copy.deepcopy(s) for s in kt.streams.values() if s["campaign_id"] == cid],
                      key=lambda s: s.get("position", 0))

    @app.get(p + "/streams/{sid}")
    def stream(sid: int, api_key: str | None = Header(None)):
        auth(api_key)
        return copy.deepcopy(kt.streams.get(sid) or nf("Stream"))

    @app.post(p + "/streams")
    def create_stream(data: dict, api_key: str | None = Header(None)):
        auth(api_key)
        for f in ("campaign_id", "schema", "type", "name", "action_type"):
            if not data.get(f):
                raise HTTPException(406, detail={f: ["required"]})
        if int(data["campaign_id"]) not in kt.campaigns:
            nf("Campaign")
        known = {o["id"] for o in kt.offers}
        for o in data.get("offers", []):
            if int(o["offer_id"]) not in known:
                raise HTTPException(406, detail={"offers": [f"offer {o['offer_id']} not found"]})
        return kt._add_stream(data)

    @app.put(p + "/streams/{sid}")
    def update_stream(sid: int, data: dict, api_key: str | None = Header(None)):
        auth(api_key)
        s = kt.streams.get(sid) or nf("Stream")
        for k, v in data.items():
            if k == "offers":
                s["offers"] = kt._offer_links(sid, v)
            elif k != "id":
                s[k] = v
        return copy.deepcopy(s)

    return app


app = create_app()
