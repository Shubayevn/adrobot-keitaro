import json

import pytest

from app.services.creator import CreatorError, parse_geo


def test_parse_geo():
    assert parse_geo("mx, AU;ro  au") == ["MX", "AU", "RO"]
    with pytest.raises(CreatorError):
        parse_geo("AUS")
    with pytest.raises(CreatorError):
        parse_geo(" , ")


def test_create_campaign(client, fake):
    r = client.post("/api/campaigns", json={"name": "test camp", "geo": "AU, MX", "offer_id": 3803})
    assert r.status_code == 201, r.text
    c = r.json()
    kt_campaign = fake.campaigns[c["id"]]
    assert kt_campaign["name"] == "test camp"
    assert kt_campaign["domain_id"] == 1 and kt_campaign["group_id"] == "1" and kt_campaign["traffic_source_id"] == 1
    assert kt_campaign["alias"]

    streams = sorted([s for s in fake.streams.values() if s["campaign_id"] == c["id"]], key=lambda s: s["position"])
    assert len(streams) == 2
    geo, offer = streams
    assert geo["schema"] == "redirect" and geo["action_payload"] == "https://google.com"
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert geo["offers"] == []
    assert [(o["offer_id"], o["share"]) for o in offer["offers"]] == [(3803, 100)]
    assert offer["filters"] == []

    # кампания сразу доступна в редакторе
    state = client.get(f"/api/campaigns/{c['id']}").json()
    assert [s["has_offers"] for s in state["streams"]] == [False, True]


def test_create_campaign_with_explicit_lookups_and_new_group(client, fake):
    r = client.post("/api/campaigns", json={
        "name": "x", "geo": "RO", "offer_id": 3749, "domain_id": 2, "traffic_source_id": 2,
        "new_group_name": "My group",
    })
    assert r.status_code == 201, r.text
    c = fake.campaigns[r.json()["id"]]
    new_group = next(g for g in fake.groups if g["name"] == "My group")
    assert c["domain_id"] == 2 and c["traffic_source_id"] == 2 and c["group_id"] == str(new_group["id"])


def test_create_campaign_validation(client, fake):
    before = len(fake.campaigns)
    assert client.post("/api/campaigns", json={"name": "", "geo": "AU", "offer_id": 3749}).status_code == 400
    assert client.post("/api/campaigns", json={"name": "a", "geo": "Australia", "offer_id": 3749}).status_code == 400
    assert client.post("/api/campaigns", json={"name": "a", "geo": "AU", "offer_id": 1}).status_code == 400
    assert len(fake.campaigns) == before


def test_stream_failure_rolls_back_campaign(client, fake, monkeypatch):
    from app.keitaro import KeitaroClient, KeitaroError

    calls = {"n": 0}
    original = KeitaroClient.create_stream

    def flaky(self, data):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeitaroError("boom", 406)
        return original(self, data)

    monkeypatch.setattr(KeitaroClient, "create_stream", flaky)
    r = client.post("/api/campaigns", json={"name": "rollback", "geo": "AU", "offer_id": 3749})
    assert r.status_code == 502
    assert "удалена" in r.json()["detail"]
    c = next(c for c in fake.campaigns.values() if c["name"] == "rollback")
    assert c["state"] == "deleted"


def test_lookups_and_offer_search(client):
    d = client.get("/api/lookups").json()
    assert d["defaults"] == {"domain_id": 1, "group_id": 1, "traffic_source_id": 1}
    assert {x["name"] for x in d["groups"]} >= {"FORTESTS"}
    found = client.get("/api/offers", params={"q": "oxys"}).json()
    assert [o["id"] for o in found] == [3802]
    by_id = client.get("/api/offers", params={"q": "3749"}).json()
    assert by_id[0]["id"] == 3749


def test_api_key_header_sent(client, fake):
    client.get("/api/campaigns")
    assert any(path.endswith("/campaigns") for _, path, _ in fake.calls)
    # body of POST campaign is JSON
    client.post("/api/campaigns", json={"name": "h", "geo": "AU", "offer_id": 3749})
    body = next(b for m, p, b in fake.calls if m == "POST" and p.endswith("/campaigns"))
    assert json.loads(body)["cost_auto"] is True


def test_group_not_created_when_validation_fails(client, fake):
    before = len(fake.groups)
    r = client.post("/api/campaigns", json={"name": "a", "geo": "AU", "offer_id": 999999, "new_group_name": "G"})
    assert r.status_code == 400
    assert len(fake.groups) == before


def test_empty_env_values_are_allowed(tmp_path):
    from app.config import Settings

    env = tmp_path / ".env"
    env.write_text("KEITARO_DEFAULT_DOMAIN_ID=\nKEITARO_DEFAULT_GROUP_ID=\nKEITARO_DEFAULT_TRAFFIC_SOURCE_ID=\n")
    s = Settings(_env_file=str(env))
    assert s.keitaro_default_domain_id is None
