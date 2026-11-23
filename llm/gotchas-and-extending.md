# Gotchas, edge cases, and how to extend

## Gotchas

- **Posters don't work standalone.** Different ports mean different origins, and the canvas gets
  tainted (posters.md). Use the platform dev stack. The failures also leave permanent
  `cinema.nop.<id>` flags in that origin's `localStorage`; clear site data to retry.
- **A failed grab is never retried on that device** (`nop.<id>`). If a file only failed because
  of a transient problem (e.g. the 20 s timeout on a slow link), that device won't try again.
  Other devices still will.
- **Drop's item format is an API Cinema depends on.** It uses `id`, `kind`, `name`, `parent`,
  `type`, `size`, `created` and `download` from `GET /api/items`. A change in Drop
  (`../airplanemode-drop/app.py`, `items()`) can break Cinema quietly. Items that fail validation
  just disappear from the library. There's no error.
- **An empty answer from Drop deletes every poster** (`tidy_posters`). That's by design, but it
  will surprise you if you point `DROP_URL` at an empty Drop.
- **A non-numeric `size`/`created` from Drop gives a 500** (`int()`/`float()` in
  `library_from_drop`). Only an unexpected Exception from the fetch becomes a 503.
- **The order of checks in `PUT /api/posters`** means a PUT can return 503 when Drop is down and
  the 60 s id cache is stale.
- **Poster browser cache**: one day. The DOM patch after an upload uses `?v=1`; other views get
  the poster on the next render. A replaced poster (same id) can show stale for up to a day.
- **`showState` "continue" triggers on any saved position**, even a few seconds (positions are
  saved every 5 s, on pause and on close). Resume only seeks if `started()`. So the button may say
  "Continue S1 · E1" and still start from 0:00.
- **Up next stops at an unplayable file.** It doesn't skip to the next playable one.
- **A folder playlist mixes audio and video** in natural order. Audio-after-video skips the
  countdown.
- **Loose top-level files** share one playlist: all of `inFolder(null)`.
- **Season from the folder name beats the file name.** `S02E05.mp4` placed in "Season 1" is
  treated as S1E5.
- **Pattern 4 (`\bE(\d{1,3})\b`) is case-sensitive.** `e05` alone isn't an episode, while
  `S01e05` is (pattern 1 is case-insensitive).
- **The `1x02` pattern needs a 2- or 3-digit episode**: `1x2` isn't matched.
- **Shows don't nest**, and a show's subtree never yields shelves. A folder of several shows
  (e.g. "TV") stays a plain folder whose children are shows: it appears as chips in the folder
  view, and the shows appear on the Shows shelf.
- **The 30 s refresh re-renders the current view** (but never while the player is open). Any
  transient DOM state (e.g. a hover) resets, and the scroll is restored from `scrollMem`.
- **The test slice markers.** `tests/test_series.mjs` depends on the literal strings
  `const nat =` and `// ---- library ----` appearing in that order, and on `lib`/`byId`/`folderById`
  being `let` variables inside the slice. Moving the TV code out of that range, adding load-time
  DOM calls, or putting a needed helper above `const nat =` breaks the test (or CI).
- **Relative URLs only.** `test_page_uses_relative_urls` fails on any `src="/..."`,
  `href="http..."` or `"/api/` string in the page. Inline SVG/data URIs are fine (the favicon is
  a `data:` URI).
- **`download:false` is cosmetic.** Don't "fix" it by refusing to stream: decision 0013 says
  streaming must always work. Drop enforces the real policy on attachment downloads.
- **`.dockerignore` doesn't exclude `llm/`** (its `*.md` matches the root only), so these notes
  get copied into the image. Add `llm` to `.dockerignore` if that matters.
- **Port 8000 is reserved on Jesse's Windows machine.** Standalone dev uses 8768 (Cinema) and
  8766 (Drop); the platform stack uses 8080.
- **Nothing has been tested on real hardware.** Codec support is per browser: MP4/H.264+AAC, WebM
  and MP3 are safe; MKV, HEVC and AC-3 often aren't. There's no transcoding.

## How to extend

### Support a new episode file-name pattern

1. Add a `[regex, m => [season|null, ep]]` entry to `EP_RES` (`static/index.html:201`). **Order
   matters**: the first match wins, and its position decides where the title starts. Put more
   specific patterns before looser ones, and use `\b` boundaries.
2. Remember the input has already been normalized (no extension, `.`/`_` turned into spaces).
3. Add assertions to the "episode numbers from file names" test in `tests/test_series.mjs`,
   including at least one **negative** (something that must *not* match, such as a year,
   resolution or camera file name like `IMG_1234`). If the pattern affects show detection or
   ordering, add files to the fixture `lib` and extend the show tests.
4. Run `node tests/test_series.mjs`.
5. Update the "Episode names understood" list in `README.md`.

### Support a new season folder name

Extend the word list in `seasonOf` (`:222`): `season|series|staffel|saison|temporada|s`, or the
specials regex at `:221`. Add the case to the "season numbers from folder names" test. Check it
doesn't swallow ordinary folder names (e.g. "Beach 2024" must stay `null`).

### Add a backend endpoint

Keep it under `/api/...` (the platform reserves its own top-level `/api` and `/admin`, but Cinema
is behind the `/cinema/` prefix). Validate every id with `ID_RE`. Never read media bytes. Use the
`X-Cinema: 1` header pattern for anything that writes. Add a test in `tests/test_cinema.py` (a
`test_` function; it runs in definition order and shares the `c` client and the fake `DROP`).

### Subtitles (planned in the README, not built)

The natural fit: `.vtt` files next to a video in Drop. `MEDIA_RE` would need to let `text/vtt`
through as a non-playable kind (or the page would read the raw Drop list), and the player would
add `<track src="drop_path + api/files/<vtt id>">`. Check Drop's `INLINE_TYPES`: `text/vtt` is
currently served as an attachment (`application/octet-stream`), and downloads may be blocked by
`nodownload`. Drop would need a change first. This is a design note, not existing behaviour.

### Change what "finished"/"started" mean

Edit `finished`/`started` (`:178-179`). They're inside the test slice, and `showState` uses them.
Re-check test 5's numbers (1499/1500 must be finished; 300/1500 must not be) and short clips
(anything under 300 s depends only on the 95% rule).

### Keep these in sync when changing the app's identity or capabilities

`app.yaml` ↔ platform `portal/apps.json` (`opens`, description) ↔ platform `compose.yaml` (image
tag, `mem_limit`) ↔ platform `Caddyfile` (`/cinema/` route). Platform CI checks the last three
exist together.
