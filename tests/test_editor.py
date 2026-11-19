"""Сценарии из видео, через HTTP API обёртки и фейковый Keitaro."""

from tests.conftest import campaign_id, kt_shares, offers_stream, shares


def fetch(client, fake):
    r = client.post(f"/api/campaigns/{campaign_id(fake)}/fetch")
    assert r.status_code == 200, r.text
    return r.json()


def link_of(stream, offer_id):
    return next(o for o in stream["offers"] if o["offer_id"] == offer_id)


def test_fetch_streams(client, fake):
    state = fetch(client, fake)
    assert [s["name"] for s in state["streams"]] == ["Flow 1", "Flow 2"]
    flow1, flow2 = state["streams"]
    assert flow1["has_offers"] is False and flow1["offers"] == []  # поток без офферов не разбираем
    assert shares(flow2) == {3749: 33, 3717: 33, 3801: 34}
    assert flow2["dirty"] is False
    assert link_of(flow2, 3749)["name"].startswith("Miaflow")


def test_add_offer_recalculates_and_push(client, fake):
    s = offers_stream(fetch(client, fake))
    r = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802})
    assert r.status_code == 200, r.text
    s = r.json()
    assert shares(s) == {3749: 25, 3717: 25, 3801: 25, 3802: 25}
    assert s["dirty"] is True
    # в Keitaro пока ничего не поменялось
    assert len(fake.streams[s["keitaro_id"]]["offers"]) == 3
    # повторный GET состояния: черновик сохранён в нашей базе
    again = offers_stream(client.get(f"/api/campaigns/{campaign_id(fake)}").json())
    assert again["dirty"] is True and len(again["offers"]) == 4

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert s["dirty"] is False
    assert kt_shares(fake, s["keitaro_id"]) == {3749: 25, 3717: 25, 3801: 25, 3802: 25}


def test_add_duplicate_and_unknown_offer(client, fake):
    s = offers_stream(fetch(client, fake))
    r = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3749})
    assert r.status_code == 400
    r = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 999999})
    assert r.status_code == 400


def test_cancel_removes_unpublished_offers(client, fake):
    s = offers_stream(fetch(client, fake))
    client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802})
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3803}).json()
    assert len(s["offers"]) == 5
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert s["dirty"] is False
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}


def test_remove_push_bring_back(client, fake):
    s = offers_stream(fetch(client, fake))
    link = link_of(s, 3717)
    s = client.post(f"/api/stream-offers/{link['id']}/remove").json()
    assert link_of(s, 3717)["status"] == "removed"
    assert link_of(s, 3717)["share"] == 0
    assert shares(s) == {3749: 50, 3717: 0, 3801: 50}
    assert s["dirty"] is True

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert kt_shares(fake, s["keitaro_id"]) == {3749: 50, 3801: 50}  # исчез из Keitaro
    assert link_of(s, 3717)["status"] == "removed"  # но остался у нас в архиве
    assert s["dirty"] is False

    s = client.post(f"/api/stream-offers/{link['id']}/bring-back").json()
    assert s["dirty"] is True
    assert shares(s) == {3749: 34, 3717: 33, 3801: 33}
    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert kt_shares(fake, s["keitaro_id"]) == {3749: 34, 3717: 33, 3801: 33}


def test_cancel_reverts_remove(client, fake):
    s = offers_stream(fetch(client, fake))
    link = link_of(s, 3801)
    client.post(f"/api/stream-offers/{link['id']}/remove")
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}
    assert link_of(s, 3801)["status"] == "active"
    assert s["dirty"] is False


def test_offers_removed_in_keitaro_become_removed_on_fetch(client, fake):
    s = offers_stream(fetch(client, fake))
    # пользователь удалил два оффера прямо в Keitaro
    kt_stream = fake.streams[s["keitaro_id"]]
    kt_stream["offers"] = [o for o in kt_stream["offers"] if o["offer_id"] == 3801]
    kt_stream["offers"][0]["share"] = 100

    s = offers_stream(fetch(client, fake))
    assert link_of(s, 3749)["status"] == "removed"
    assert link_of(s, 3717)["status"] == "removed"
    assert shares(s) == {3749: 0, 3717: 0, 3801: 100}
    assert s["dirty"] is False

    s = client.post(f"/api/stream-offers/{link_of(s, 3749)['id']}/bring-back").json()
    assert shares(s) == {3749: 50, 3717: 0, 3801: 50}
    assert s["dirty"] is True


def test_pin_scenario_from_video(client, fake):
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()  # 25 x 4
    pinned = link_of(s, 3749)
    s = client.post(f"/api/stream-offers/{pinned['id']}/pin", json={"pinned": True}).json()
    assert link_of(s, 3749)["pinned"] is True and link_of(s, 3749)["share"] == 25

    # удаляем один — запиненный остаётся 25, остальные делят 75
    s = client.post(f"/api/stream-offers/{link_of(s, 3717)['id']}/remove").json()
    assert shares(s) == {3749: 25, 3717: 0, 3801: 38, 3802: 37}
    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert kt_shares(fake, s["keitaro_id"]) == {3749: 25, 3801: 38, 3802: 37}

    # возвращаем — запиненный по-прежнему 25
    s = client.post(f"/api/stream-offers/{link_of(s, 3717)['id']}/bring-back").json()
    assert link_of(s, 3749)["share"] == 25
    assert sum(o["share"] for o in s["offers"]) == 100
    assert shares(s) == {3749: 25, 3717: 25, 3801: 25, 3802: 25}

    # pin переживает fetch
    s = client.post(f"/api/streams/{s['id']}/push").json()
    s = offers_stream(fetch(client, fake))
    assert link_of(s, 3749)["pinned"] is True


def test_manual_share_pins_and_validates(client, fake):
    s = offers_stream(fetch(client, fake))
    a, b = link_of(s, 3749), link_of(s, 3717)
    s = client.post(f"/api/stream-offers/{a['id']}/share", json={"share": 60}).json()
    assert shares(s) == {3749: 60, 3717: 20, 3801: 20}
    assert link_of(s, 3749)["pinned"] is True
    r = client.post(f"/api/stream-offers/{b['id']}/share", json={"share": 50})
    assert r.status_code == 400  # 60 + 50 > 100
    r = client.post(f"/api/stream-offers/{b['id']}/share", json={"share": 101})
    assert r.status_code == 400


def test_push_blocked_without_active_offers(client, fake):
    s = offers_stream(fetch(client, fake))
    for o in s["offers"]:
        s = client.post(f"/api/stream-offers/{o['id']}/remove").json()
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 400
    assert len(fake.streams[s["keitaro_id"]]["offers"]) == 3


def test_remove_new_offer_drops_it(client, fake):
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    s = client.post(f"/api/stream-offers/{link_of(s, 3802)['id']}/remove").json()
    assert 3802 not in shares(s)
    assert s["dirty"] is False
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}  # ровно как в Keitaro


def test_remove_then_bring_back_before_push_is_clean(client, fake):
    s = offers_stream(fetch(client, fake))
    link = link_of(s, 3749)
    client.post(f"/api/stream-offers/{link['id']}/remove")
    s = client.post(f"/api/stream-offers/{link['id']}/bring-back").json()
    assert s["dirty"] is False
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}


def test_push_detects_keitaro_mismatch(client, fake, monkeypatch):
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    # Keitaro «молча» не сохранил изменения
    monkeypatch.setattr("app.keitaro.KeitaroClient.update_stream", lambda self, sid, data: {})
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 502
    s = offers_stream(client.get(f"/api/campaigns/{campaign_id(fake)}").json())
    assert s["dirty"] is True  # не помечаем опубликованным


def test_keitaro_auth_error_is_reported(client, fake):
    fake.api_key = "other"
    r = client.post(f"/api/campaigns/{campaign_id(fake)}/fetch")
    assert r.status_code == 502
    assert "401" in r.json()["detail"]


def test_csrf_guard_blocks_posts_without_header(client, fake):
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)
    r = bare.post(f"/api/campaigns/{campaign_id(fake)}/fetch")
    assert r.status_code == 403
    assert bare.get("/health").status_code == 200


# ---------- регрессии по итогам ревью ----------

def test_manual_share_survives_remove_and_bring_back(client, fake):
    s = offers_stream(fetch(client, fake))
    a, b = link_of(s, 3749), link_of(s, 3717)
    client.post(f"/api/stream-offers/{a['id']}/share", json={"share": 60})
    client.post(f"/api/streams/{s['id']}/push")
    s = client.post(f"/api/stream-offers/{a['id']}/share", json={"share": 40}).json()
    assert shares(s) == {3749: 40, 3717: 30, 3801: 30}
    client.post(f"/api/stream-offers/{b['id']}/remove")
    s = client.post(f"/api/stream-offers/{b['id']}/bring-back").json()
    assert shares(s) == {3749: 40, 3717: 30, 3801: 30}
    assert s["dirty"] is True


def test_pin_is_saved_immediately_and_does_not_change_shares(client, fake):
    s = offers_stream(fetch(client, fake))  # 33/33/34
    a = link_of(s, 3749)
    s = client.post(f"/api/stream-offers/{a['id']}/pin", json={"pinned": True}).json()
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}
    assert s["dirty"] is False
    s = offers_stream(fetch(client, fake))
    assert link_of(s, 3749)["pinned"] is True
    # следующая операция уже учитывает pin
    s = client.post(f"/api/stream-offers/{link_of(s, 3717)['id']}/remove").json()
    assert shares(s) == {3749: 33, 3717: 0, 3801: 67}


def test_disabled_offer_in_keitaro_shown_as_removed(client, fake):
    s = offers_stream(fetch(client, fake))
    kt_stream = fake.streams[s["keitaro_id"]]
    kt_stream["offers"].append({"id": 1, "stream_id": s["keitaro_id"], "offer_id": 3805, "share": 0, "state": "disabled"})
    s = offers_stream(fetch(client, fake))
    assert link_of(s, 3805)["status"] == "removed"
    s = client.post(f"/api/stream-offers/{link_of(s, 3805)['id']}/bring-back").json()
    assert shares(s)[3805] == 25


def test_keitaro_side_removal_without_renormalization_makes_stream_dirty(client, fake):
    s = offers_stream(fetch(client, fake))
    kt_stream = fake.streams[s["keitaro_id"]]
    kt_stream["offers"] = [o for o in kt_stream["offers"] if o["offer_id"] != 3749]  # 33 + 34 = 67
    s = offers_stream(fetch(client, fake))
    assert shares(s) == {3749: 0, 3717: 50, 3801: 50}
    assert s["dirty"] is True and s["total_share"] == 100
    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert kt_shares(fake, s["keitaro_id"]) == {3717: 50, 3801: 50}


def test_push_refuses_when_keitaro_changed_after_fetch(client, fake):
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    # кто-то добавил оффер прямо в Keitaro
    fake.streams[s["keitaro_id"]]["offers"].append(
        {"id": 2, "stream_id": s["keitaro_id"], "offer_id": 3805, "share": 10, "state": "active"})
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 400
    assert "Fetch" in r.json()["detail"]
    assert 3805 in kt_shares(fake, s["keitaro_id"])  # ничего не затёрли


def test_push_reports_if_keitaro_touched_other_fields(client, fake, monkeypatch):
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    kid = s["keitaro_id"]
    original = __import__("app.keitaro", fromlist=["KeitaroClient"]).KeitaroClient.update_stream

    def wipe_filters(self, sid, data):
        res = original(self, sid, data)
        fake.streams[sid]["filters"] = []
        fake.streams[sid]["schema"] = "redirect"
        return res

    fake.streams[kid]["filters"] = [{"name": "country", "mode": "accept", "payload": ["RO"]}]
    monkeypatch.setattr("app.keitaro.KeitaroClient.update_stream", wipe_filters)
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 502
    assert "schema" in r.json()["detail"] and "filters" in r.json()["detail"]
    # офферы при этом сохранены и помечены опубликованными
    state = offers_stream(client.get(f"/api/campaigns/{campaign_id(fake)}").json())
    assert state["dirty"] is False


def test_wrong_keitaro_url_gives_clear_error(kt):
    import httpx
    import pytest

    from app.keitaro import KeitaroClient, KeitaroError

    html = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html>login</html>")))
    with pytest.raises(KeitaroError, match="KEITARO_URL"):
        KeitaroClient(kt.settings, http=html).list_campaigns()

    redirect = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(301, headers={"location": "https://x/"})))
    with pytest.raises(KeitaroError, match="редирект"):
        KeitaroClient(kt.settings, http=redirect).list_campaigns()


# ---------- регрессии по второму ревью ----------

def test_unpin_then_remove_bring_back_gives_even_split(client, fake):
    s = offers_stream(fetch(client, fake))
    a, b = link_of(s, 3749), link_of(s, 3717)
    client.post(f"/api/stream-offers/{a['id']}/share", json={"share": 60})
    client.post(f"/api/streams/{s['id']}/push")  # 60/20/20
    client.post(f"/api/stream-offers/{a['id']}/pin", json={"pinned": False})
    client.post(f"/api/stream-offers/{b['id']}/remove")
    s = client.post(f"/api/stream-offers/{b['id']}/bring-back").json()
    assert shares(s) == {3749: 34, 3717: 33, 3801: 33}  # +1 тому, у кого опубликовано больше
    assert s["dirty"] is True


def test_scalar_filter_payload_does_not_break_push(client, fake):
    s = offers_stream(fetch(client, fake))
    fake.streams[s["keitaro_id"]]["filters"] = [{"name": "bot", "mode": "reject", "payload": True}]
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    r = client.post(f"/api/streams/{s['id']}/push")
    assert r.status_code == 200, r.text


def test_all_pinned_and_one_deleted_in_keitaro_is_normalized(client, fake):
    s = offers_stream(fetch(client, fake))
    for o in s["offers"]:
        client.post(f"/api/stream-offers/{o['id']}/pin", json={"pinned": True})
    kt_stream = fake.streams[s["keitaro_id"]]
    kt_stream["offers"] = [o for o in kt_stream["offers"] if o["offer_id"] != 3749]
    s = offers_stream(fetch(client, fake))
    assert s["total_share"] == 100 and s["dirty"] is True
    assert client.post(f"/api/streams/{s['id']}/push").status_code == 200


def test_pinned_over_100_in_keitaro_is_normalized(client, fake):
    s = offers_stream(fetch(client, fake))
    for o in s["offers"]:
        client.post(f"/api/stream-offers/{o['id']}/pin", json={"pinned": True})
    for o in fake.streams[s["keitaro_id"]]["offers"]:
        o["share"] = 60
    s = offers_stream(fetch(client, fake))
    assert shares(s) == {3749: 34, 3717: 33, 3801: 33}
    assert all(not o["pinned"] for o in s["offers"])


def test_cancel_keeps_normalization_after_keitaro_side_removal(client, fake):
    s = offers_stream(fetch(client, fake))
    kt_stream = fake.streams[s["keitaro_id"]]
    kt_stream["offers"] = [o for o in kt_stream["offers"] if o["offer_id"] != 3749]  # 33 + 34
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert s["total_share"] == 100 and s["dirty"] is True


def test_pin_state_consistent_after_remove_bring_back_and_fetch(client, fake):
    s = offers_stream(fetch(client, fake))
    a = link_of(s, 3749)
    client.post(f"/api/stream-offers/{a['id']}/pin", json={"pinned": True})
    client.post(f"/api/stream-offers/{a['id']}/remove")
    s = client.post(f"/api/stream-offers/{a['id']}/bring-back").json()
    assert link_of(s, 3749)["pinned"] is False
    s = offers_stream(fetch(client, fake))
    assert link_of(s, 3749)["pinned"] is False


def test_manual_share_then_cancel_keeps_pin_as_local_setting(client, fake):
    s = offers_stream(fetch(client, fake))
    a = link_of(s, 3749)
    client.post(f"/api/stream-offers/{a['id']}/share", json={"share": 60})
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert shares(s) == {3749: 33, 3717: 33, 3801: 34}
    assert s["dirty"] is False
    assert link_of(s, 3749)["pinned"] is True  # pin — локальная настройка, Cancel её не трогает


def test_push_keeps_disabled_links_in_keitaro(client, fake):
    s = offers_stream(fetch(client, fake))
    kid = s["keitaro_id"]
    fake.streams[kid]["offers"].append({"id": 3, "stream_id": kid, "offer_id": 3805, "share": 0, "state": "disabled"})
    s = offers_stream(fetch(client, fake))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 3802}).json()
    assert client.post(f"/api/streams/{s['id']}/push").status_code == 200
    states = {o["offer_id"]: o["state"] for o in fake.streams[kid]["offers"]}
    assert states[3805] == "disabled"


def test_keitaro_url_with_api_suffix_is_accepted(kt):
    from app.config import Settings
    from app.keitaro import KeitaroClient

    s = Settings(_env_file=None, keitaro_url="https://t.example.com/admin_api/v1/")
    assert KeitaroClient(s)._base == "https://t.example.com/admin_api/v1"
