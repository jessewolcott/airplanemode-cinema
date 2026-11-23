# Backend: `app.py`

A single FastAPI module with no database. `docs_url`, `redoc_url` and `openapi_url` are all
`None` (`app.py:42`), so there's no `/docs` page.

## Configuration (`app.py:31-40`)

| Name | Value | Notes |
|---|---|---|
| `DATA` | `$DATA_DIR` or `/data` | the tests point it at a temp dir |
| `POSTERS` | `DATA / "posters"` | created lazily on the first poster PUT |
| `DROP_URL` | `$DROP_URL` or `http://drop:8000`, trailing `/` stripped | server-side Drop address |
| `DROP_PATH` | `$DROP_PATH` or `../drop/` | returned to the browser as-is; must end in `/` because the page appends `api/files/<id>` |
| `ID_RE` | `^[0-9a-f]{16}$` | Drop's id format (Drop uses the same regex) |
| `MEDIA_RE` | `^(video\|audio)/[A-Za-z0-9.+-]+$` | the only types Cinema accepts |
| `MAX_POSTER` | 300 KiB | per poster |
| `MAX_POSTERS` | 5000 | files in the posters dir |

## Reading Drop: `library_from_drop()` (`app.py:54-75`)

`_fetch_drop()` (`:45`) does a blocking `urllib.request.urlopen(f"{DROP_URL}/api/items",
timeout=5)` and `json.load`s the result. It runs in a worker thread through
`anyio.to_thread.run_sync`. The module-level name `fetch_drop = _fetch_drop` (`:50`) is the seam
the tests replace.

**Any exception** (connection refused, timeout, bad JSON) is logged and becomes
`HTTPException(503, "Can't reach Drop right now. Is it running?")`.

Drop's `GET /api/items` returns `{version, items: [...], admin, used, cap, ...}`. Each item has
`id`, `kind` (`file` | `folder` | `text`), `name`, `parent`, `type` (files), `size`, `created`,
`download` (true unless that item or an ancestor folder has `nodownload`), `kept`, `blocked_by`,
and more (see `../airplanemode-drop/app.py`, `items()`). Cinema reads only a few of these fields,
and treats every one as untrusted input:

1. Skip anything that isn't a `dict`, or whose `str(id)` doesn't match `ID_RE`. This drops
   traversal attempts like `"../../etc"`.
2. `parent` is kept only if it matches `ID_RE`. Otherwise it's `None` (the top level).
3. `kind == "folder"` → `{id, name[:200], parent}`.
4. `kind == "file"` **and** `type` matches `MEDIA_RE` → `{id, name[:200], type,
   kind: type.split("/")[0]` (`"video"`/`"audio"`)`, size: int, parent, created: float,
   download: bool(default True)}`. Text items, PDFs, images and malformed types such as
   `video/mp4"><script>` are dropped.
5. **Parent fix-up** (`:71-74`): for folders and media alike, if `parent` isn't one of the
   folder ids Drop sent, it's set to `None`, so an orphan shows at the top level instead of
   vanishing. (The test case: a song whose parent `"f"*16` doesn't exist ends up with
   `parent: None`.)

The function returns `(folders, media)`, in Drop's order (newest first). The page sorts everything
itself.

Not handled server-side: folder cycles (the page's `folderPath` stops after 12 levels), and a
non-numeric `size`/`created` (the `int()`/`float()` would raise, giving a 500). Drop is a trusted
sibling in practice.

## `GET /api/library` (`app.py:87-96`)

```python
folders, media = await library_from_drop()
ids = {m["id"] for m in media}
_known.update(ids=ids, at=time.time())       # refresh the "media Drop has" cache
await anyio.to_thread.run_sync(tidy_posters, ids)   # delete orphan posters
have = {p.stem for p in POSTERS.iterdir()}   # which posters exist
m["poster"] = m["id"] in have                # per media item
return {"drop_path": DROP_PATH, "folders": folders, "media": media}
```

Response shape:

```json
{
  "drop_path": "../drop/",
  "folders": [{"id": "…16 hex…", "name": "Season 1", "parent": "…|null"}],
  "media":   [{"id": "…", "name": "Coastal.Life.S01E01.mp4", "type": "video/mp4", "kind": "video",
               "size": 123, "parent": "…|null", "created": 1732200000.0, "download": true,
               "poster": false}]
}
```

### Orphan cleanup: `tidy_posters(ids)` (`:78-84`)

On every successful library call, every file in `POSTERS` whose `Path.stem` isn't a current media
id gets deleted. So a poster disappears once Drop deletes or expires the file, or once its type
stops being media. It runs only after Drop answered successfully (a 503 raises first). But **if
Drop answers with an empty list**, all posters are deleted. That's by design: posters are cheap
to regrab.

## Posters

Storage path: `poster_path(iid)` (`:99`) checks `ID_RE` (else 404 "No such poster.") and returns
`POSTERS/<id>.img`. The extension is always `.img`, whatever the format. The id is the only part
of the path that comes from the client, and it's regex-checked.

### `GET /api/posters/{id}` (`:105-112`)

- 404 "No poster yet." if the file is missing.
- The content type is sniffed from the stored bytes: it starts with `RIFF` → `image/webp`,
  otherwise `image/jpeg`. (It reads the whole file to check 4 bytes, which is fine at ≤ 300 KB.)
- Headers: `Cache-Control: private, max-age=86400` and `X-Content-Type-Options: nosniff`.
  Because of the 1-day cache, the page appends `?v=1` to the URL right after it uploads a poster
  (see posters.md).

### `PUT /api/posters/{id}` (`:115-140`), checks in order

1. The header `X-Cinema: 1` is required, else **403** "Missing request header." It's a CSRF
   guard: a cross-site form can't set custom headers, and a cross-site `fetch` with one needs a
   CORS preflight, which Cinema never answers.
2. `poster_path(iid)` → **404** if the id is malformed. (The test sends `..%2f..%2fx` and gets 404.)
3. **Only for known media:** if `_known` is more than 60 s old, the id set is rebuilt from
   `library_from_drop()` (which can itself raise **503**). If the id isn't in it → **404** "Drop
   has no such file." This blocks posters for PDFs, text items and ids that don't exist, so the
   poster dir can't be used as general storage.
4. The body is read as a stream and the size checked **while reading**: once over `MAX_POSTER`
   → **413** "That poster is too big." So at most about 300 KB plus one chunk is ever buffered.
5. Magic bytes: JPEG `FF D8 FF`, or WebP `RIFF....WEBP` (bytes 0-3 and 8-11). Otherwise **415**
   "Posters must be JPEG or WebP." The `Content-Type` header is ignored. (SVG is rejected on
   purpose: it could carry script.)
6. `POSTERS.mkdir(parents=True, exist_ok=True)`.
7. Count cap: if this is a **new** poster and the dir already holds `MAX_POSTERS` (5000) files →
   **507** "Too many posters." Replacing an existing poster is always allowed.
8. Atomic write: write `<id>.tmp`, then `replace()` it onto `<id>.img`. Returns `{"ok": true}`.

Note: any client on the hotspot can **overwrite** any poster (there's no "already exists" check,
and no auth beyond the header). That's accepted: posters are cosmetic, and the page only uploads
when `poster` is false.

## Errors and the page route

- `@app.exception_handler(HTTPException)` (`:143`) returns `{"detail": ...}` with the status and
  any headers. The page shows `detail` when the library fails (`index.html:311`).
- `GET /` (`:148`) returns `static/index.html` with `Cache-Control: no-cache`, so new releases
  show up straight away. There's no static mount: the page is the only static file, and it
  inlines everything.

## Concurrency notes

- `_known` is a module-level dict shared by all requests. There's no lock: a race only means an
  extra refresh from Drop.
- File operations in the poster handlers run on the event loop (they're small). `tidy_posters`
  runs in a thread.
- uvicorn runs a single worker (Dockerfile `CMD`).
