# Cinema (AirplaneMode app): notes for Claude

Plays the videos and music on Drop. FastAPI app in `app.py` (library + posters), one page in
`static/index.html` (library, player, poster grabbing, per-device resume in localStorage).

Part of AirplaneMode: the platform repo is `../airplanemode`. Read its `CLAUDE.md` for the
environment notes and `docs/app-contract.md` for the rules this app must follow. The library
is Drop's (`../airplanemode-drop`), so changes to Drop's item format affect this app.

## Commands

```powershell
docker compose up -d --build         # standalone dev: Cinema :8768 + Drop :8766 (no posters: cross-origin)
python tests/test_cinema.py          # API tests (CI runs these before building)
node tests/test_series.mjs           # series logic (episode parsing, shows, watch order), from the page's code
```

The real test bed is the platform dev stack (`../airplanemode`, compose.dev.yaml builds this
repo): same origin, so posters work and Drop's "Play in Cinema" appears.

## Rules

- **Never proxy media.** The browser streams from Drop (`drop_path` + `api/files/<id>`). Cinema's
  memory limit is 64m.
- The page uses **relative URLs** (a test checks it). Drop's path comes from `api/library`.
- Anything from Drop is input: ids must match `ID_RE`, types `MEDIA_RE`. Posters are stored by
  id only, must be JPEG/WebP by magic bytes, ≤ 300 KB, and only for media Drop has.
- Honour Drop's `download: false`: `controlslist="nodownload"`, no context menu. It's a
  courtesy, not protection; streaming always works.
- Resume positions are per device (localStorage `cinema.p.<id>`). No accounts.
- **TV series** live in the page (`parseEp`, `seasonOf`, `isShow`, `buildShows`, `showState`),
  between `const nat =` and `// ---- library ----`: `tests/test_series.mjs` runs exactly that
  slice under Node, so keep it free of DOM work at load time. A show's subfolders are seasons,
  never shelves; `#show=<id>[&s=<n>]` is its page; the player's playlist is the show's whole
  episode list. Add a case to the test for any new file-name pattern.

## Releasing

Push a `vX.Y.Z` tag. CI tests, then publishes `ghcr.io/jessewolcott/airplanemode-cinema:X.Y.Z`
(arm64 + amd64). **Ask Jesse before pushing a release tag.** Released: 0.1.0, 0.1.1 (TV series).
