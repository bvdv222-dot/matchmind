"""API: REST views, the live WebSocket feed and ask-this-view (agents off: deterministic overlays and fallbacks)."""
import os
import time

import pytest

os.environ["MM_AGENTS"] = "off"

from fastapi.testclient import TestClient  # noqa: E402

from api.app import app  # noqa: E402
from contracts.models import OverlayMessage  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def match(client):
    fx = client.get("/api/fixtures", params={"round": 5}).json()["fixtures"][0]
    r = client.post("/api/matches/start", json={"match_id": fx["match_id"], "speed": 600}).json()
    return r


def test_health_and_config(client):
    assert client.get("/api/health").json()["ok"]
    cfg = client.get("/api/config").json()
    assert cfg["agents"] is False and "es" in cfg["languages"]


def test_live_feed(client, match):
    kinds, overlays = {}, []
    with client.websocket_connect(f"/ws/matches/{match['match_id']}?persona=analyst&lang=es") as ws:
        ws.send_json({"type": "prefs", "persona": "casual", "lang": "en"})
        t0 = time.time()
        while time.time() - t0 < 40:
            m = ws.receive_json()
            kinds[m["type"]] = kinds.get(m["type"], 0) + 1
            if m["type"] == "overlay":
                overlays.append(m["data"])
            if m["type"] == "finished":
                break
    assert kinds.get("hello") == 1 and kinds.get("finished") == 1
    assert kinds.get("frame", 0) > 10 and kinds.get("state", 0) > 10
    assert overlays, "moments should produce overlays"
    for o in overlays:
        OverlayMessage.model_validate({k: v for k, v in o.items()})
        assert o["verified"]


def test_dashboard_and_player(client, match):
    mid = match["match_id"]
    d = client.get(f"/api/matches/{mid}/dashboard").json()
    assert set(d["teams"]) == {d["home"], d["away"]}
    assert d["windows"] and d["facts"]
    team = d["teams"][d["home"]]
    assert "xg" in team["vs_expected"] and team["network"]["nodes"]
    pid = d["top_players"][0]["player_id"]
    p = client.get(f"/api/matches/{mid}/players/{pid}").json()
    assert p["player_id"] == pid and "match" in p
    assert client.get(f"/api/matches/{mid}/players/nope").status_code == 404


def test_ask_falls_back_to_facts(client, match):
    r = client.post(f"/api/matches/{match['match_id']}/ask",
                    json={"question": "Who has had more of the ball?", "team_id": match["meta"]["home"]["team_id"]})
    a = r.json()
    assert r.status_code == 200 and a["verified"] and a["source"] == "fallback"
    assert a["context_sent"] and a["answer"].startswith("Here is what the data on this screen shows")


def test_unknown_match(client):
    assert client.get("/api/matches/nope/state").status_code == 404


def test_feed_reaches_the_bus_and_questions_the_store(client, match):
    from api.app import SERVICES
    sent = list(SERVICES["bus"].sent)
    kinds = {m["kind"] for m in sent}
    assert {"event", "state", "overlay"} <= kinds
    assert any(m["kind"] == "frame" for m in sent)
    asks = SERVICES["store"].items["asks"]
    assert asks and asks[-1]["match_id"] == match["match_id"] and asks[-1]["context_sent"]


def test_event_hubs_batches_by_match():
    import asyncio

    from api.bus import EventHubsBus

    class Batch:
        def __init__(self, size):
            self.items, self.size = [], size

        def add(self, ev):
            if len(self.items) >= self.size:
                raise ValueError("full")
            self.items.append(ev)

    class Producer:
        def __init__(self):
            self.sent, self.keys = [], []

        async def create_batch(self, partition_key=None):
            self.keys.append(partition_key)
            return Batch(2)

        async def send_batch(self, b):
            self.sent.append(len(b.items))

    bus = EventHubsBus.__new__(EventHubsBus)
    bus._producer = Producer()
    asyncio.run(bus.publish("M-9", [{"kind": "event", "data": {"i": i}} for i in range(5)]))
    assert bus._producer.sent == [2, 2, 1] and set(bus._producer.keys) == {"M-9"}


def test_ask_is_rate_limited(client, match, monkeypatch):
    import api.app as appmod
    monkeypatch.setattr(appmod, "ASK_PER_MINUTE", 2)
    appmod._asks.clear()
    url = f"/api/matches/{match['match_id']}/ask"
    codes = [client.post(url, json={"question": "Who leads?"}, headers={"x-forwarded-for": "203.0.113.9"}).status_code
             for _ in range(3)]
    assert codes == [200, 200, 429]
