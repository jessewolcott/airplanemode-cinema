"""Cinema API tests.  Run: python tests/test_cinema.py"""
import os
import re
import threading
import time
import sys
import tempfile
from pathlib import Path

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="cinema-test-"), ADMIN_URL="", CINEMA_POLL_WAIT="0.3")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import app as cinema  # noqa: E402

H = {"X-Cinema": "1"}
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
FILM, SONG, DOC, MOVIES, KIDS = "a" * 16, "b" * 16, "c" * 16, "d" * 16, "e" * 16
DROP = {"items": [
    {"id": MOVIES, "kind": "folder", "name": "Movies", "parent": None},
    {"id": KIDS, "kind": "folder", "name": "Kids", "parent": MOVIES},
    {"id": FILM, "kind": "file", "name": "Big Film.mp4", "type": "video/mp4", "size": 900, "parent": KIDS,
     "created": 1.0, "download": False},
    {"id": SONG, "kind": "file", "name": "song.mp3", "type": "audio/mpeg", "size": 50, "parent": "f" * 16, "created": 2.0},
    {"id": DOC, "kind": "file", "name": "ticket.pdf", "type": "application/pdf", "size": 9, "parent": None},
    {"id": "1" * 16, "kind": "text", "name": "note", "text": "hi", "parent": None},
    {"id": "../../etc", "kind": "file", "name": "evil.mp4", "type": "video/mp4"},
    {"id": "2" * 16, "kind": "file", "name": "x.html", "type": "video/mp4\"><script>", "parent": None},
]}


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json()


def test_page_uses_relative_urls():
    html = c.get("/").text
    assert 'fetch("api/library"' in html and '"/api/' not in html
    assert not re.search(r'(src|href)="(https?:|//|/[^/])', html), re.findall(r'(?:src|href)="[^"]*"', html)


def test_page_has_home_button():
    """App contract item 10: the AirplaneMode home button in the library header and the player."""
    html = c.get("/").text
    links = re.findall(r'<a class="am-home" href="([^"]*)" aria-label="AirplaneMode home"', html)
    assert len(links) == 2 and set(links) == {"../"}, links
    assert ">AirplaneMode</a>" not in html   # the old text pill is gone


def test_library_is_drops_media():
    lib = ok(c.get("/api/library"))
    assert lib["drop_path"] == "../drop/"
    assert {f["id"] for f in lib["folders"]} == {MOVIES, KIDS}
    media = {m["id"]: m for m in lib["media"]}
    assert set(media) == {FILM, SONG}, media            # no pdf, text, bad ids or odd types
    assert media[FILM]["kind"] == "video" and media[FILM]["parent"] == KIDS and media[FILM]["download"] is False
    assert media[SONG]["parent"] is None                # its folder isn't in Drop's list
    assert media[SONG]["download"] is True and not media[FILM]["poster"]


def test_drop_down():
    def boom():
        raise OSError("connection refused")
    cinema.fetch_drop = boom
    try:
        r = c.get("/api/library")
        assert r.status_code == 503 and "Drop" in r.json()["detail"]
    finally:
        cinema.fetch_drop = lambda: DROP


def test_posters():
    ok(c.get("/api/library"))
    assert c.get(f"/api/posters/{FILM}").status_code == 404
    assert c.put(f"/api/posters/{FILM}", content=JPEG).status_code == 403           # no header
    assert c.put(f"/api/posters/{FILM}", content=b"<svg/>", headers=H).status_code == 415
    assert c.put(f"/api/posters/{FILM}", content=JPEG + b"x" * cinema.MAX_POSTER, headers=H).status_code == 413
    assert c.put(f"/api/posters/{DOC}", content=JPEG, headers=H).status_code == 404  # not media on Drop
    assert c.put("/api/posters/..%2f..%2fx", content=JPEG, headers=H).status_code == 404
    ok(c.put(f"/api/posters/{FILM}", content=JPEG, headers=H))
    r = c.get(f"/api/posters/{FILM}")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert {m["id"]: m["poster"] for m in ok(c.get("/api/library"))["media"]}[FILM] is True
    assert [p.name for p in cinema.POSTERS.iterdir()] == [f"{FILM}.img"]


def test_posters_for_deleted_files_go():
    ok(c.put(f"/api/posters/{FILM}", content=JPEG, headers=H))
    gone = {"items": [i for i in DROP["items"] if i["id"] != FILM]}
    cinema.fetch_drop = lambda: gone
    try:
        ok(c.get("/api/library"))
        assert not (cinema.POSTERS / f"{FILM}.img").exists()
    finally:
        cinema.fetch_drop = lambda: DROP


# ---------------- Sync Watch ----------------
def seat(token):
    return {**H, "X-Seat": token}


def test_watch_party_start_join_and_control():
    cinema._known["at"] = 0                  # the last test left Drop's list without FILM in the cache
    assert c.post("/api/watch", json={"item": FILM}).status_code == 403                 # no header
    assert c.post("/api/watch", json={"item": DOC}, headers=H).status_code == 404      # not media
    assert c.post("/api/watch", json={"item": FILM, "pos": -1}, headers=H).status_code == 400
    assert c.post("/api/watch", json={"item": FILM, "pos": "10"}, headers=H).status_code == 400
    a = ok(c.post("/api/watch", json={"item": FILM, "pos": 30, "playing": False}, headers=H))
    code, ta = a["code"], a["token"]
    st = a["state"]
    assert st["item"] == FILM and st["pos"] == 30 and st["playing"] is False and st["you"] == 0
    assert [p["code"] for p in ok(c.get("/api/watch"))["parties"]] == [code]
    b = ok(c.post(f"/api/watch/{code.lower()}/join", json={}, headers=H))
    tb = b["token"]
    assert b["state"]["you"] == 1 and len(b["state"]["seats"]) == 2
    assert ok(c.post(f"/api/watch/{code}/join", json={"token": tb}, headers=H))["token"] == tb   # same seat back
    # play: the position runs on from the moment on the box's clock
    st = ok(c.post(f"/api/watch/{code}/act", json={"type": "play", "pos": 31.5}, headers=seat(tb)))
    assert st["playing"] and st["pos"] == 31.5 and st["last"]["type"] == "play"
    room = cinema.parties.get(code)
    time.sleep(0.2)
    assert 31.6 < room.position() < 32.5
    st = ok(c.post(f"/api/watch/{code}/act", json={"type": "pause"}, headers=seat(ta)))   # no pos: where it is now
    assert not st["playing"] and 31.6 < st["pos"] < 32.5
    st = ok(c.post(f"/api/watch/{code}/act", json={"type": "seek", "pos": 600}, headers=seat(ta)))
    assert st["pos"] == 600 and not st["playing"]                                      # seeking keeps play/pause
    # changing the file: everyone's up-next fires at once, the second one changes nothing
    st = ok(c.post(f"/api/watch/{code}/act", json={"type": "item", "item": SONG}, headers=seat(tb)))
    v = st["version"]
    assert st["item"] == SONG and st["pos"] == 0 and st["playing"]
    assert ok(c.post(f"/api/watch/{code}/act", json={"type": "item", "item": SONG}, headers=seat(ta)))["version"] == v
    assert c.post(f"/api/watch/{code}/act", json={"type": "item", "item": DOC}, headers=seat(ta)).status_code == 404
    assert c.post(f"/api/watch/{code}/act", json={"type": "dance"}, headers=seat(ta)).status_code == 400
    assert c.post(f"/api/watch/{code}/act", json={"type": "play"}, headers=seat("nope")).status_code == 403
    assert c.get(f"/api/watch/{code}/state", headers={"X-Seat": "nope"}).status_code == 403
    # leaving: the last one out ends the party
    ok(c.post(f"/api/watch/{code}/leave", headers=seat(ta)))
    assert len(ok(c.get(f"/api/watch/{code}/state", headers={"X-Seat": tb}))["seats"]) == 1
    ok(c.post(f"/api/watch/{code}/leave", headers=seat(tb)))
    assert c.get(f"/api/watch/{code}/state", headers={"X-Seat": tb}).status_code == 404
    assert ok(c.get("/api/watch"))["parties"] == []


def test_watch_long_poll_wakes_on_a_change():
    a = ok(c.post("/api/watch", json={"item": FILM}, headers=H))
    code, ta = a["code"], a["token"]
    tb = ok(c.post(f"/api/watch/{code}/join", json={}, headers=H))["token"]
    v = a["state"]["version"] + 1                                   # after b joined
    t0 = time.time()
    st = ok(c.get(f"/api/watch/{code}/state", params={"since": v}, headers={"X-Seat": tb}))
    assert st["version"] == v and 0.25 < time.time() - t0 < 2       # nothing changed: waited
    out = {}
    t = threading.Thread(target=lambda: out.update(st=c.get(f"/api/watch/{code}/state", params={"since": v},
                                                             headers={"X-Seat": tb}).json()))
    t.start()
    time.sleep(0.1)
    ok(c.post(f"/api/watch/{code}/act", json={"type": "pause", "pos": 5}, headers=seat(ta)))
    t.join(5)
    assert out["st"]["playing"] is False and out["st"]["pos"] == 5
    assert abs(ok(c.get("/api/watch/clock"))["now"] - time.time() * 1000) < 1000
    for tok in (ta, tb):
        c.post(f"/api/watch/{code}/leave", headers=seat(tok))


def test_watch_party_nobody_polls_ends():
    a = ok(c.post("/api/watch", json={"item": FILM}, headers=H))
    tb = ok(c.post(f"/api/watch/{a['code']}/join", json={}, headers=H))["token"]
    room = cinema.parties.get(a["code"])
    room.seats[1].seen -= 120                                    # b closed the page without leaving
    assert ok(c.get("/api/watch"))["parties"][0]["watching"] == 1
    cinema.parties.sweep()
    assert a["code"] in cinema.parties.rooms                     # a is still here
    for s in room.seats:
        s.seen -= cinema.GONE_AFTER + 1
    cinema.parties.sweep()
    assert a["code"] not in cinema.parties.rooms                 # nobody for 10 minutes: over
    assert c.get(f"/api/watch/{a['code']}/state", headers={"X-Seat": tb}).status_code == 404


def test_watch_names_come_from_whos_who():
    people = {"phone": {"id": "p1", "name": "Sam", "avatar": "🦊"}}

    async def fake_whois(request):
        return people.get(request.headers.get("x-test-device"))
    old, cinema.whois = cinema.whois, fake_whois
    try:
        sam = {**H, "X-Test-Device": "phone"}
        a = ok(c.post("/api/watch", json={"item": FILM}, headers=sam))
        assert (a["state"]["seats"][0]["name"], a["state"]["seats"][0]["avatar"]) == ("Sam", "🦊")
        p = ok(c.get("/api/watch"))["parties"][0]
        assert p["host"] == "Sam" and p["avatar"] == "🦊" and p["watching"] == 1 and p["item"] == FILM
        again = ok(c.post(f"/api/watch/{a['code']}/join", json={}, headers=sam))      # Sam's other browser
        assert again["token"] == a["token"]
        guest = ok(c.post(f"/api/watch/{a['code']}/join", json={}, headers=H))
        assert guest["state"]["seats"][1]["name"] == "Traveller"
        for tok in (a["token"], guest["token"]):
            c.post(f"/api/watch/{a['code']}/leave", headers=seat(tok))
    finally:
        cinema.whois = old


if __name__ == "__main__":
    cinema.fetch_drop = lambda: DROP
    with TestClient(cinema.app) as c:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok  ", name)
