"""Cinema: watch and listen to what's on Drop, on every device on the AirplaneMode hotspot.

Cinema has no files of its own. Its library is Drop's: videos and audio, shelved by Drop's
folders. The browser streams the media straight from Drop (same address, under /drop/), so
Cinema never touches the bytes and stays small. Drop's "downloads off" setting still applies
to saving copies; playing is always allowed.

API (relative to the app's root; the platform serves it at /cinema/):
  GET  api/library          Drop's folders + the playable files in them, and where to stream from
  GET  api/posters/{id}     a poster image (a frame grabbed from the video by the first browser to see it)
  PUT  api/posters/{id}     store one (JPEG/WebP body, header "X-Cinema: 1")

Where you are in each film lives in the browser (per device), so every tablet on the plane
keeps its own place. Nothing needs an account.

Sync Watch (watch parties): several phones play the same file in step, each on its own
earbuds, each streaming from Drop itself. A party is an amrooms room (the platform's Rooms
SDK) holding the file, playing or paused, and the position at a moment on the box's clock.
Anyone in the party can play, pause, seek or change the file; every phone long-polls and
steers its own player to match (pages: `syncStep`).
  GET  api/watch                       open parties on this hotspot
  GET  api/watch/clock                 {now}: the box's clock in ms, for the page's offset
  POST api/watch {item, pos, playing}  start one -> {code, token, state}
  POST api/watch/{code}/join {token?}  a seat (or yours back) -> {token, state}
  GET  api/watch/{code}/state?since=N  long-poll (seat token in "X-Seat")
  POST api/watch/{code}/act {type: play|pause|seek|item, pos?, item?}
  POST api/watch/{code}/leave
POSTs need "X-Cinema: 1". Names and emoji come from who's who (the AirplaneMode menu).
"""
import asyncio
import contextlib
import json
import logging
import math
import os
import re
import time
import urllib.request
from pathlib import Path

import anyio
from amrooms import Room, RoomError, Rooms, whois
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

log = logging.getLogger("cinema")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HERE = Path(__file__).parent
DATA = Path(os.getenv("DATA_DIR", "/data"))
POSTERS = DATA / "posters"
# Drop's API as this container sees it, and Drop's address as the browser sees it.
DROP_URL = os.getenv("DROP_URL", "http://drop:8000").rstrip("/")
DROP_PATH = os.getenv("DROP_PATH", "../drop/")
ID_RE = re.compile(r"^[0-9a-f]{16}$")
MEDIA_RE = re.compile(r"^(video|audio)/[A-Za-z0-9.+-]+$")
MAX_POSTER = 300 * 1024
MAX_POSTERS = 5000



class Party(Room):
    """A watch party. No bots, no game: people join and leave at any time."""
    max_seats = 30
    away_after = 60.0
    poll_wait = float(os.getenv("CINEMA_POLL_WAIT", "20"))

    def __init__(self, code, seed=None, item=None, pos=0.0, playing=True):
        super().__init__(code, seed)
        self.item, self.playing_now = item, bool(playing)
        self.pos, self.at = max(0.0, float(pos)), now_ms()
        self.last = None                      # {"by": name, "type": ...} for "Sam paused"

    def empty(self):
        """Nobody seen for 10 minutes. People who close the page without pressing Leave stay
        seated (as away) until then, so a phone that locked mid-film can come straight back."""
        now = time.monotonic()
        return not any(s.human and not s.left and now - s.seen < GONE_AFTER for s in self.seats)

    def position(self, at=None):
        """Seconds into the file at `at` (ms on the box's clock)."""
        at = now_ms() if at is None else at
        return self.pos + ((at - self.at) / 1000 if self.playing_now else 0.0)

    def apply(self, i, kind, pos=None, item=None):
        if kind == "item":
            if item == self.item:
                return                          # several phones' "up next" fire at once: once is enough
            self.item, self.pos, self.playing_now = item, 0.0, True
        elif kind in ("play", "pause", "seek"):
            self.pos = self.position() if pos is None else pos
            if kind != "seek":
                self.playing_now = kind == "play"
        else:
            raise RoomError(400, "Unknown action.")
        self.at = now_ms()
        self.last = {"by": self.seats[i].name, "type": kind}
        self.changed()

    def view(self, token):
        me = self.seat_of(token)
        now = time.monotonic()
        return {"code": self.code, "version": self.version, "item": self.item, "playing": self.playing_now,
                "pos": self.pos, "at": self.at, "now": now_ms(), "you": me, "last": self.last,
                "seats": [self.seat_info(i, me, now) for i in range(len(self.seats))
                          if not self.seats[i].left]}

    def summary(self):
        here = [s for i, s in enumerate(self.seats) if not self.away(i)]
        return {"code": self.code, "item": self.item, "playing": self.playing_now,
                "host": self.host.name if self.host else "?", "avatar": self.host.avatar if self.host else None,
                "watching": len(here)}


def now_ms():
    return time.time() * 1000


GONE_AFTER = 600.0       # seconds: a party nobody has polled for this long is over


parties = Rooms(Party, max_rooms=50, idle=6 * 3600, empty_grace=30)


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(parties.sweep_forever())
    yield
    task.cancel()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _fetch_drop():
    with urllib.request.urlopen(f"{DROP_URL}/api/items", timeout=5) as r:
        return json.load(r)


fetch_drop = _fetch_drop      # tests replace this
_known = {"ids": set(), "at": 0.0}


async def library_from_drop():
    try:
        data = await anyio.to_thread.run_sync(fetch_drop)
    except Exception as e:
        log.warning("can't reach Drop at %s: %s", DROP_URL, e)
        raise HTTPException(503, "Can't reach Drop right now. Is it running?")
    folders, media = [], []
    for i in data.get("items", []):
        if not isinstance(i, dict) or not ID_RE.match(str(i.get("id", ""))):
            continue
        parent = i.get("parent") if ID_RE.match(str(i.get("parent") or "")) else None
        if i.get("kind") == "folder":
            folders.append({"id": i["id"], "name": str(i.get("name", ""))[:200], "parent": parent})
        elif i.get("kind") == "file" and MEDIA_RE.match(str(i.get("type", ""))):
            media.append({"id": i["id"], "name": str(i.get("name", ""))[:200], "type": i["type"],
                          "kind": i["type"].split("/")[0], "size": int(i.get("size") or 0), "parent": parent,
                          "created": float(i.get("created") or 0), "download": bool(i.get("download", True))})
    folder_ids = {f["id"] for f in folders}
    for x in folders + media:              # a parent Drop didn't send: show it at the top
        if x["parent"] not in folder_ids:
            x["parent"] = None
    return folders, media


def tidy_posters(ids):
    """Posters for files that are gone from Drop."""
    if not POSTERS.exists():
        return
    for p in POSTERS.iterdir():
        if p.stem not in ids:
            p.unlink(missing_ok=True)


@app.get("/api/library")
async def library():
    folders, media = await library_from_drop()
    ids = {m["id"] for m in media}
    _known.update(ids=ids, at=time.time())
    await anyio.to_thread.run_sync(tidy_posters, ids)
    have = {p.stem for p in POSTERS.iterdir()} if POSTERS.exists() else set()
    for m in media:
        m["poster"] = m["id"] in have
    return {"drop_path": DROP_PATH, "folders": folders, "media": media}


def poster_path(iid):
    if not ID_RE.match(iid):
        raise HTTPException(404, "No such poster.")
    return POSTERS / f"{iid}.img"


@app.get("/api/posters/{iid}")
async def get_poster(iid: str):
    p = poster_path(iid)
    if not p.exists():
        raise HTTPException(404, "No poster yet.")
    kind = "image/webp" if p.read_bytes()[:4] == b"RIFF" else "image/jpeg"
    return FileResponse(p, media_type=kind, headers={"Cache-Control": "private, max-age=86400",
                                                     "X-Content-Type-Options": "nosniff"})


@app.put("/api/posters/{iid}")
async def put_poster(iid: str, request: Request):
    if request.headers.get("x-cinema") != "1":
        raise HTTPException(403, "Missing request header.")
    p = poster_path(iid)
    if not await drop_has(iid):             # only for files Drop actually has
        raise HTTPException(404, "Drop has no such file.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_POSTER:
            raise HTTPException(413, "That poster is too big.")
    jpeg = body[:3] == b"\xff\xd8\xff"
    webp = body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    if not (jpeg or webp):
        raise HTTPException(415, "Posters must be JPEG or WebP.")
    POSTERS.mkdir(parents=True, exist_ok=True)
    if not p.exists() and sum(1 for _ in POSTERS.iterdir()) >= MAX_POSTERS:
        raise HTTPException(507, "Too many posters.")
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(p)
    return {"ok": True}


async def drop_has(iid):
    """Whether Drop has this media file (its list is re-read at most once a minute, or on a miss
    after 5 s, so a file added a moment ago is found)."""
    if not ID_RE.match(str(iid or "")):
        return False
    age = time.time() - _known["at"]
    if age > 60 or (iid not in _known["ids"] and age > 5):
        _known["ids"] = {m["id"] for m in (await library_from_drop())[1]}
        _known["at"] = time.time()
    return iid in _known["ids"]


# ---------------- Sync Watch ----------------
def need_header(request: Request):
    if request.headers.get("x-cinema") != "1":
        raise HTTPException(403, "Missing request header.")


async def body(request: Request):
    need_header(request)
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Send JSON.")
    if not isinstance(data, dict):
        raise HTTPException(400, "Send a JSON object.")
    return data


def seconds(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v < 7 * 86400:
        raise HTTPException(400, "Position must be a number of seconds.")
    return float(v)


@app.get("/api/watch")
async def open_parties():
    return {"parties": [p.summary() for p in parties.open_lobbies(20)]}


@app.get("/api/watch/clock")
async def clock():
    return {"now": now_ms()}


@app.post("/api/watch")
async def start_party(request: Request):
    data = await body(request)
    item = data.get("item")
    pos = seconds(data.get("pos", 0))
    who = await whois(request)
    if not await drop_has(item):
        raise HTTPException(404, "Drop has no such file.")
    room = parties.create(item=item, pos=pos, playing=data.get("playing", True) is not False)
    token = room.join(None, who=who)
    return {"code": room.code, "token": token, "state": room.view(token)}


@app.post("/api/watch/{code}/join")
async def join_party(code: str, request: Request):
    data = await body(request)
    who = await whois(request)
    room = parties.get(code)
    token = room.join(None, data.get("token") or request.headers.get("x-seat"), who=who)
    return {"token": token, "state": room.view(token)}


@app.get("/api/watch/{code}/state")
async def party_state(code: str, request: Request, since: int = -1):
    room = parties.get(code)
    token = request.headers.get("x-seat", "")
    room.need_seat(token)
    room.seen(token)
    await room.wait(since)
    if room.closed or room.seat_of(token) is None:
        raise HTTPException(404, "This watch party has ended.")
    room.seen(token)
    return room.view(token)


@app.post("/api/watch/{code}/act")
async def party_act(code: str, request: Request):
    data = await body(request)
    room = parties.get(code)
    token = request.headers.get("x-seat", "")
    i = room.need_seat(token)
    room.seen(token)
    kind = data.get("type")
    item = data.get("item")
    if kind == "item" and not await drop_has(item):
        raise HTTPException(404, "Drop has no such file.")
    pos = seconds(data["pos"]) if data.get("pos") is not None else None
    async with room.lock:
        room.apply(i, kind, pos=pos, item=item)
    return room.view(token)


@app.post("/api/watch/{code}/leave")
async def leave_party(code: str, request: Request):
    need_header(request)
    room = parties.get(code)
    room.leave(request.headers.get("x-seat", ""))
    parties.sweep()                     # the last one out: the party ends
    return {"ok": True}


@app.exception_handler(RoomError)
async def room_error(_req, exc):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(HTTPException)
async def http_error(_req, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})
