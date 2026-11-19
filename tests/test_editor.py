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
