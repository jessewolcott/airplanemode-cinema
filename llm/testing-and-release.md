# Testing, build, CI and release

## Python API tests: `tests/test_cinema.py`

Run with `python tests/test_cinema.py` (needs `fastapi`, `uvicorn` and `httpx` for `TestClient`;
CI installs `httpx==0.28.1`). It isn't pytest: the `__main__` block runs every global whose name
starts with `test_`, in definition order, and prints `ok  <name>`. The first failing `assert`
stops the run.

Setup:

- `DATA_DIR` is set to a fresh `tempfile.mkdtemp()` **before** importing `app`, so posters go to
  a temp dir.
- The repo root goes on `sys.path`, then `import app as cinema`.
- `cinema.fetch_drop = lambda: DROP` replaces the network call to Drop. `DROP` is a fake
  `/api/items` payload with: folders Movies → Kids; a video `Big Film.mp4` in Kids with
  `download: False`; an `audio/mpeg` song whose parent `"f"*16` doesn't exist; a PDF; a text
  item; an item with id `"../../etc"`; and a file with type `video/mp4"><script>`.
- `c` is a module global `TestClient`, created in `__main__` (so the test functions can't be
  imported and run by pytest as they are).

| Test | Checks |
|---|---|
| `test_page_uses_relative_urls` | the page contains `fetch("api/library"` and no `"/api/`, and no `src=`/`href=` starts with `http:`, `https:`, `//` or `/x`. Keeps the app working under any path prefix (`/cinema/`) and offline |
| `test_library_is_drops_media` | `drop_path == "../drop/"`; only the two real folders; only FILM and SONG in media (no PDF, text, bad id or bad type); FILM `kind=video`, parent Kids, `download False`; SONG's missing parent → `None`, `download` defaults to True; `poster` false |
| `test_drop_down` | `fetch_drop` raises → 503 with "Drop" in `detail` |
| `test_posters` | GET before upload → 404; PUT without the header → 403; SVG body → 415; JPEG over `MAX_POSTER` → 413; poster for the PDF id → 404; `..%2f..%2fx` → 404; a valid JPEG → 200; GET returns the same bytes, `image/jpeg`, `nosniff`; the library now says `poster: True`; the posters dir holds exactly `<FILM>.img` |
| `test_posters_for_deleted_files_go` | after Drop stops listing FILM, a library call deletes its poster |

## Series tests: `tests/test_series.mjs` (runs the page's own code)

Run with `node tests/test_series.mjs`. It needs only Node built-ins (`node:fs`, `node:assert/strict`),
with no npm install. Output: `ok  <name>` for each test and `5 passed`.

**How it works** (`:7-19`):

1. It reads `static/index.html` as text.
2. It slices from the first `const nat =` to the first `// ---- library ----`, and asserts that
   both were found and in that order.
3. It stubs the browser globals the slice touches:
   - `globalThis.localStorage` is backed by a `Map` (so `mem`, `pos`, `savePos` work for real);
   - `globalThis.document.createElement()` returns an object whose `canPlayType` gives
     `"probably"` (so `playable()` is true).
4. It wraps the slice in `new Function(slice + "return { parseEp, seasonOf, buildShows,
   showState, epLong, epShort, titleOf, savePos, setLib, shows }")()`. `setLib(l)` assigns the
   slice's own `let lib, byId, folderById` closure variables, which is why those must stay `let`
   and stay inside the slice. `shows()` returns the current `shows` map (it's reassigned by
   `buildShows`).

Because the test runs the exact code that ships, there's no copy to keep in sync. But anything in
the slice that runs **at load time** must work without a DOM. `$`, `esc` and the SVG constants are
defined *before* `const nat =` and are not in the slice; calling them would throw
`ReferenceError`.

The tests:

1. **episode numbers from file names**: `parseEp` on `S01E02` with a title, `s2e10`, `1x03 -
   Title`, `Episode 4 - Title`, `ep_12`, and the negatives `Holiday 2024`, `1080p sunset`.
2. **season numbers from folder names**: `seasonOf` for Season 1, season_02, S3, Series 4, "5",
   Staffel 2, Specials, Extras, "Show Season 6 (2019)"; null for Kids, Movies, "Beach 2024".
3. **which folders are shows**: a fixture library (built with the helpers `F(i, name, parent)`
   and `M(i, name, parent, kind)`; ids are hex-padded numbers, media ids are 100+i) → exactly
   Coastal Life, Night Ferry and Ocean Trip. Not Movies/Kids, not TV, and no season folders.
4. **episodes in watch order across seasons, specials last**: Coastal Life →
   `[[1,1],[1,2],[1,3],[2,1],[2,2],[0,null]]`, seasons `[1,2,0]`; the labels "S1 · E2 · Low
   Tide", "E1 · New Shores", "Special · Behind the Scenes"; Night Ferry's unnamed Part A/B →
   seasons 1/2 by folder order; a one-season show → "E2"; a film keeps `tidy` ("Whale Song").
5. **what to watch next in a show**: `showState` goes start → continue (300/1500) → next (1499/1500
   is finished) → next into season 2 after finishing S1 → done.

Tests 3-5 share state: `buildShows` mutates the fixture objects, and `savePos` fills the stubbed
storage in order.

## Not covered by automated tests

DOM rendering, the player, poster grabbing, Media Session, keyboard handling and the
`download:false` attributes. Check those by hand in the **platform dev stack**
(`../airplanemode`: `docker compose -f compose.yaml -f compose.dev.yaml up -d --build` →
`http://localhost:8080/cinema/`). There, Drop is same-origin, posters work, and Drop shows *Play
in Cinema*. Standalone (`docker compose up -d --build` here → `http://localhost:8768`, Drop on
`:8766`) works for everything except posters. None of this has been verified on real hardware
yet; mark anything as *untested* accordingly.

## Docker image (`Dockerfile`)

- `python:3.12-slim`; `pip install -r requirements.txt` (fastapi 0.115.6, uvicorn 0.34.0); then
  `COPY . .`.
- `.dockerignore` excludes `.git`, `.github`, `.vscode`, `tests`, `__pycache__`, root `*.md`,
  `compose.yaml`, `docs/screenshots` and `docs/icon.svg`. **Note:** `*.md` in `.dockerignore`
  only matches the build-context root, and `llm/` isn't listed, so this folder's Markdown files
  end up in the image unless `llm` is added to `.dockerignore`. That's harmless but wasteful.
- It runs as system user `cinema` (uid 10001). `/data` is created and chowned before `VOLUME
  /data`, so a fresh named volume inherits the owner.
- `EXPOSE 8000`; `CMD uvicorn app:app --host 0.0.0.0 --port 8000` (single worker). There's no
  healthcheck.

## CI: `.github/workflows/image.yml`

Triggers: push to `main`, push of `v*` tags, and pull requests. Permissions: `contents: read`,
`packages: write`. One job, `build`:

1. checkout, `setup-python` 3.12;
2. **API tests**: `pip install -r requirements.txt httpx==0.28.1 && python tests/test_cinema.py`;
3. **Series tests**: `node tests/test_series.mjs` (the runner's preinstalled Node; no setup-node);
4. QEMU + Buildx;
5. log in to `ghcr.io` with `GITHUB_TOKEN` (not on PRs);
6. `docker/metadata-action` tags: `type=ref,event=branch` (→ `:main`) and
   `type=semver,pattern={{version}}` (tag `v1.2.3` → `:1.2.3`);
7. build `linux/arm64,linux/amd64` (the R6S is arm64), and push unless it's a PR.

A test failure stops the job before any image is built.

## Releasing

1. Make sure CI is green on `main`.
2. **Ask Jesse first**, then push a tag `vX.Y.Z`. That publishes
   `ghcr.io/jessewolcott/airplanemode-cinema:X.Y.Z`. Released so far: `0.1.0`, `0.1.1` (TV series).
3. In the platform repo (`../airplanemode`), bump the pinned tag in `compose.yaml`
   (`image: ghcr.io/jessewolcott/airplanemode-cinema:0.1.1`; never `latest`). The platform CI also
   checks that the `Caddyfile` route (`handle_path /cinema/*`) and the `portal/apps.json` entry
   (including `opens`) exist.
4. If the manifest changes (description, `opens`, env), keep `app.yaml` and the platform's
   `portal/apps.json` entry in sync by hand.

Commit messages in this project end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
(platform `CLAUDE.md`).
