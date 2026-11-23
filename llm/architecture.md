# Architecture

## Where Cinema sits

AirplaneMode is a set of self-hosted, offline apps that run on a travel router (target: NanoPi
R6S). The **platform** repo (`../airplanemode`) holds the Caddy front door, the landing page, the
admin service and `compose.yaml`. Apps are separate repos that ship as pinned container images.
Cinema is one of them. Its sibling **Drop** (`../airplanemode-drop`) is a file drop: people upload
files and folders to the box.

Cinema's design is recorded in platform decision `docs/decisions/0013-cinema-drop-folders-app-switches.md`:

- Cinema is its own app with **no files of its own**. Its library is Drop's, and Drop's folders
  are its shelves.
- The browser streams straight from `/drop/api/files/<id>` (same origin, with Range), so Cinema
  never handles media and fits in 64 MB.
- Posters are frames that the first browser grabs and uploads. Resume positions stay in each
  browser: per device, with no accounts.
- Drop's admin-only "downloads off" (`nodownload`) is **not DRM**. Streaming always works, and
  Cinema only hides the browser's save option.
- "Open with" works through the platform's `portal/apps.json`. Cinema's `opens` entry
  (`{from: "drop", types: ["video/*","audio/*"], url: "/cinema/#play={id}"}`, also in
  `app.yaml`) makes Drop show *Play in Cinema* on matching files.

## Request flow on the box

```
browser ──► Caddy (LAN_IP:80)
             ├─ /cinema/*  handle_path → cinema:8000   (prefix stripped; app sees "/" and "/api/...")
             └─ /drop/*    handle_path → drop:8000
```

(Platform `Caddyfile`: `redir /cinema /cinema/` and `handle_path /cinema/* { reverse_proxy cinema:8000 }`.)

1. The browser loads `/cinema/`. `app.py:148` serves `static/index.html` with `Cache-Control: no-cache`.
2. The page calls `fetch("api/library")`, a **relative** URL that resolves to `/cinema/api/library`.
3. `app.py` calls Drop **inside the Docker network** at `DROP_URL` (`http://drop:8000/api/items`),
   filters the result and returns `{drop_path, folders, media}`.
4. To play a file, the page sets `<video src = drop_path + "api/files/" + id>`. `drop_path`
   defaults to `../drop/`, which is relative to `/cinema/`, so it becomes `/drop/api/files/<id>`.
   The browser talks to Drop directly through Caddy. Drop serves Range requests (206) with
   `Content-Disposition: inline` for `video/*` and `audio/*`, so seeking works and "downloads
   off" never blocks playback (Drop only blocks attachment downloads and `?dl=1`).
5. Posters: the page grabs a frame in the browser and `PUT`s it to `api/posters/<id>`. Other
   devices `GET` it.

There are two addresses for Drop on purpose:

| Env var | Default | Who uses it |
|---|---|---|
| `DROP_URL` | `http://drop:8000` | the Cinema container (server-to-server, `app.py:35`) |
| `DROP_PATH` | `../drop/` | the browser (handed out in `api/library`, `app.py:36`) |

## Why same-origin matters

Poster grabbing draws a `<video>` frame onto a `<canvas>` and reads it back with `toBlob`. That
only works if the video isn't cross-origin (the canvas would be "tainted"), so it needs Drop on the
same origin as Cinema. On the box and in the platform dev stack (`../airplanemode`,
`compose.dev.yaml` builds `../airplanemode-cinema`), both apps sit behind one Caddy, so it works.
In this repo's **standalone** `compose.yaml`, Cinema runs on `:8768` and Drop on `:8766` with
`DROP_PATH: http://localhost:8766/`. Those are different origins, so posters fail quietly and
everything else works.

Same-origin is also why Drop's "Play in Cinema" and the admin cookie (`am_admin`) work across apps.

## Memory budget: 64 MB

`app.yaml` (`memory: 64m`), the standalone `compose.yaml` (`mem_limit: 64m`) and the platform
compose (`${CINEMA_MEM:-64m}`) all cap Cinema at 64 MB. That's possible only because:

- media bytes never pass through Cinema;
- the library is rebuilt per request from Drop's JSON, with no cache besides a set of ids (`_known`);
- poster uploads are capped at 300 KB and buffered in memory only up to that cap (`app.py:125-129`).

**Never add a media proxy, transcoder or thumbnailer (ffmpeg) to Cinema.** That breaks the
budget and goes against decision 0013. Thumbnails are made in the browser instead.

## State

| Where | What | Lifetime |
|---|---|---|
| `/data/posters/<id>.img` (volume `cinema-data`) | poster JPEG/WebP per media id | until Drop no longer lists the id |
| browser `localStorage` (`cinema.*`) | resume position, duration, "can't make a poster" flags | per device, per origin |
| Drop | the files, folders, names, `download` flag | Drop's own expiry/keep rules |

There is no database, no accounts and no server-side watch history.

## Repo layout

```
app.py                 FastAPI service (library, posters, page)
static/index.html      the whole UI (CSS + JS inline, no build step, no external assets)
tests/test_cinema.py   API tests (TestClient, Drop faked)
tests/test_series.mjs  series logic tests: slices JS out of index.html and runs it in Node
Dockerfile             python:3.12-slim, uvicorn, non-root uid 10001, VOLUME /data
compose.yaml           standalone dev: Cinema :8768 + Drop :8766 (built from ../airplanemode-drop)
app.yaml               AirplaneMode app manifest (id, image, path /cinema/, memory, needs, opens, env)
requirements.txt       fastapi==0.115.6, uvicorn==0.34.0
.github/workflows/image.yml   tests, then a multi-arch image to ghcr.io
.vscode/tasks.json     Standalone up/down, API tests
docs/icon.svg, docs/screenshots/   README assets
```

The page loads **no external resources**: no CDN, no fonts, and the icons are inline SVG. That's
required, because the box is offline. A test enforces relative URLs (see testing-and-release.md).
