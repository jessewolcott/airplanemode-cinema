"""Cinema API tests.  Run: python tests/test_cinema.py"""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="cinema-test-"))
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


if __name__ == "__main__":
    cinema.fetch_drop = lambda: DROP
    with TestClient(cinema.app) as c:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok  ", name)
