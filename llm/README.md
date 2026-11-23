# Cinema: how it's built (reference notes)

Cinema is an AirplaneMode app that plays the videos and music stored on **Drop**, the platform's
file-sharing app. It has no media of its own. A small FastAPI service (`app.py`, 150 lines) reads
Drop's item list, keeps the video and audio files, and sends them to the browser. It also stores
poster images. Everything else lives in one page, `static/index.html` (about 580 lines of HTML, CSS
and plain JS, with no build step). That page does the shelves, TV-series detection, routing, the
player, per-device resume in `localStorage`, and poster grabbing. The browser streams media
**straight from Drop** (`/drop/api/files/<id>`, which supports HTTP Range). Cinema never proxies
media bytes, so it runs in a 64 MB container. Its only server-side state is a folder of small
JPEG/WebP posters, which the first browser to show a video grabs from a frame of that video and
uploads.

This folder is checked in (`.dockerignore` lists `llm`, so it stays out of the image). It's written for LLMs and engineers coming to
the repo cold. Line references (`file:line`) are to the code as of release 0.1.2 (2026-11-22);
re-check them if the code has moved.

## Files

| File | What it covers |
|---|---|
| [architecture.md](architecture.md) | The big picture: platform, Drop, same-origin streaming, data flow, the 64 MB budget, repo layout |
| [backend.md](backend.md) | `app.py` in full: `api/library` (reading and validating Drop), posters GET/PUT, limits, orphan cleanup, errors |
| [library-and-routing.md](library-and-routing.md) | The page's loading, hash routing, home shelves, cards, folder view, show page, refresh loop |
| [tv-series.md](tv-series.md) | `parseEp`, `seasonOf`, `isShow`, `buildShows`/`addShow`, labels, `showState`, with worked examples |
| [player.md](player.md) | Video vs audio, resume, progress saving, finished/started rules, up next, Media Session, keyboard, idle UI, `download:false` |
| [posters.md](posters.md) | Client-side frame grabbing (canvas, cover-crop, crossOrigin), the queue, server checks |
| [storage-keys.md](storage-keys.md) | Every `localStorage` key and in-memory structure the page keeps |
| [testing-and-release.md](testing-and-release.md) | `tests/test_cinema.py`, how `tests/test_series.mjs` slices the page's code, CI, Docker, releasing |
| [sync-watch.md](sync-watch.md) | Watch parties: the `Party` room (amrooms), its routes, and how each phone follows (`syncStep`, `ownEvent`, clock offset) |
| [gotchas-and-extending.md](gotchas-and-extending.md) | Known traps, edge cases, and recipes for common changes (such as adding a new file-name pattern) |

## Ten-second orientation

- Backend: `app.py`. `GET /api/library`, `GET|PUT /api/posters/{id}`, the watch-party routes
  under `/api/watch` (see [sync-watch.md](sync-watch.md)), and `GET /` for the page.
- Frontend: `static/index.html`. Its sections are marked by comments: helpers and memory
  (`:221`), TV series (`:257`), Sync Watch decisions (`:337`), `// ---- library ----` (`:358`),
  routing (`:503`), player (`:522`), Sync Watch parties (`:633`), posters (`:801`). (These
  section lines are as of 0.2.0; the other files' line references are as of 0.1.2.)
- Tests: `python tests/test_cinema.py` (API) and `node tests/test_series.mjs` (series logic,
  executed from the page's own source).
- Rules that must not break: never proxy media; use only relative URLs in the page; treat
  everything from Drop as input; keep the series slice free of DOM work at load time; ask
  before pushing `v*` tags.
