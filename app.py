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
"""
import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path

import anyio
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

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


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
    if time.time() - _known["at"] > 60:     # only for files Drop actually has
        _known["ids"] = {m["id"] for m in (await library_from_drop())[1]}
        _known["at"] = time.time()
    if iid not in _known["ids"]:
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


@app.exception_handler(HTTPException)
async def http_error(_req, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})
