# The page: loading, routing, home, folders, show page

Everything is in `static/index.html`, one `<script>` block (`:190-607`). There's no framework:
views are built as HTML strings and assigned with `innerHTML`, and every value from Drop goes
through `esc()` (`:192`, which escapes `& < > " '`). Two top-level containers: `#libView` (header,
`#crumbs`, `#lib`) and `#player` (a fixed overlay). Only one is visible at a time.

## Helpers (`:191-225`)

| Helper | Does |
|---|---|
| `$` | `document.querySelector` |
| `nat(a,b)` | natural sort by `.name` (`localeCompare` with `numeric: true, sensitivity: "base"`), so `E2` < `E10` and case is ignored |
| `tidy(name)` | strips the extension (2-5 alphanumerics), turns `.`/`_` into spaces, collapses spaces; falls back to the raw name |
| `clock(s)` | `m:ss` or `h:mm:ss` |
| `hue(str)` / `gradient(s)` | a deterministic placeholder gradient from a string hash |
| `playable(m)` | `document.createElement(m.kind).canPlayType(m.type) !== ""`; decides the "won't play on this device" dimming |
| `src(m)` | `lib.drop_path + "api/files/" + m.id`, the stream URL |
| `inFolder(fid)` | media whose `parent` is `fid` (`null` = top), natural order |
| `subfolders(fid)` | folders whose `parent` is `fid`, natural order |
| `folderPath(fid)` | ancestors from the top down, capped at 12 (guards against cycles) |
| `folderLabel(fid)` | `"Movies / Kids"` |
| `countBelow(fid)` | number of media in a folder and all its descendants |

Global state: `lib` (the last `api/library` response), `byId` (media id → item), `folderById`,
`shows` (see tv-series.md).

## Loading (`load()`, `:308-323`)

1. `fetch("api/library", {cache: "no-store"})`. If it fails or isn't OK, `#lib` becomes an
   "The library isn't reachable" panel with the server's `detail` and a *Try again* button, and
   the function returns.
2. It rebuilds `byId` and `folderById`, then calls `buildShows()`. This mutates media items with
   `show`, `season`, `ep` and `epTitle`.
3. It sets the header's "add in Drop" link (`#dropLink`) to `lib.drop_path`. The static
   `href="../drop/"` is only the default.
4. `route()` renders the current view, then `posterQueue()` starts or continues poster grabbing.

The header (`.top`, shared by home, folder and show views): the brand ("Cinema", `href="#"`,
the library start, never out of the app) on the left; on the right a `nav` with the "add in
Drop" pill and the AirplaneMode home button `a.am-home` (`href="../"`, house SVG, 44 x 44 px,
accent focus ring; app contract item 10). It replaced the old "AirplaneMode" text pill. `.top`
pads with `env(safe-area-inset-*)` (the page sets `viewport-fit=cover`).

**Refresh loop** (`:607`): `setInterval(() => { if (player hidden) load(); }, 30000)`. It picks
up new files on Drop every 30 s, but never while something is playing. Each refresh replaces
`lib` with fresh objects and re-renders through `route()`, which restores the scroll position
from `scrollMem`.

## Routing (`:442-455`)

The state lives in `location.hash`:

| Hash | View |
|---|---|
| *(empty)* or anything unrecognized | home (`renderHome`) |
| `#play=<id>` | player (`openPlayer`). Drop's *Play in Cinema* links here (`/cinema/#play={id}`) |
| `#folder=<id>` | folder view (`renderFolder`) |
| `#show=<id>` or `#show=<id>&s=<n>` | show page (`renderShow`), optionally on season `n` |

Parsing: `/^(play|folder|show)=([0-9a-f]{16})(?:&s=(\d{1,3}))?$/`. Ids are checked against the
same 16-hex format as the server.

- `route()` does nothing until `lib` has loaded.
- `#play=<unknown id>` → closes the player and renders home (the hash stays as it was).
- Every non-play route calls `closePlayer()` first. So browser **Back** from the player (a hash
  change) stops playback and saves the position.
- `go(hash)` sets `location.hash`, or calls `route()` directly if the hash is already that value.
  Without that, re-navigating to the same hash would do nothing.
- `scrollMem[hash]` stores `window.scrollY` on scroll while the player is hidden. `route()`
  scrolls back to it, so returning from the player lands where you were.
- `renderFolder` on a show id redirects to `#show=`. Unknown folder or show ids redirect home
  (`go("")`).

## Cards (`card(m, opts)`, `:333-350`)

Each card is an `<a class="card" href="#play=<id>">`:

- **Poster area**: the background is `gradient(artFor(m))`. `artFor` (`:332`) gives the show name,
  the folder label, or the file name, so every card in a show or folder shares one colour. The
  placeholder icon is a note (audio) or film (video without a poster). If `m.poster` is true, an
  `<img src="api/posters/<id>" loading="lazy">` fades in on load (`.on`).
- **Duration badge** (video only): `pos.d` if the device has a position, else the cached
  `mem d.<id>` (from earlier playback or poster grabbing). There's no badge until the device has
  seen the file's metadata.
- **Progress bar** if `started(p)`: width `t/d`.
- **Title**: `opts.title`, or `titleOf(m)` (the episode label for shows, `tidy(name)` otherwise).
  The `title` attribute holds the raw file name.
- **Meta line**: `"won't play on this device"` if not `playable`. Otherwise, joined with ` · `:
  `opts.status` or `"<clock> left"` (started), or `"watched"` (finished), plus, when
  `opts.where`, where it's from (`epLong(m)` for episodes, the folder label otherwise).
- Audio cards get the `sq` class (square, narrower). Unplayable cards get `cant` (50% opacity).
  They stay clickable, and the player explains.

`posterBox(m, art, extra)` (`:325`) is the same poster markup without the link. The show card,
show header and episode rows use it.

`showCard(sh)` (`:351-360`) links to `#show=<id>`. Its face is the current episode's poster, else
any episode with a poster. Its meta: `"<epLong> · in progress"` (continue), `"Next: <epLong>"`,
`"watched"`, or for a fresh show `"N seasons · M episodes"`. The season count leaves out
specials, and the "N seasons ·" part appears only when the show has more than one season entry.

## Home (`renderHome()`, `:362-391`)

If Drop has no media: an empty state that explains how to load files into Drop and tap **keep**,
with an *Open Drop* button. Otherwise these shelves, in order:

1. **Continue** (horizontal row, at most 12, newest `at` first):
   - films and songs that aren't in a show and are `started` (in progress, not finished), shown
     with `card(m, {where: true})`;
   - **one card per show** whose `showState` is `continue` or `next`, rendered as
     `card(st.m, {title: sh.name, where: true, status: mode === "next" ? "Next up" : ""})`. So the
     title is the show name, and the meta gives the episode (`S2 · E1 · …`) plus progress or
     "Next up". Clicking it plays that episode directly.
2. **Shows**: every show, sorted by name with `nat`, as `showCard`s.
3. **One shelf per folder** that directly holds media and isn't a show or inside one. It's a
   depth-first walk in natural order (`walk` at `:385`). A show's subtree is skipped entirely, so
   season folders never become shelves. The shelf title is the full path label ("Movies / Kids"),
   linking to `#folder=<id>`. Folders with only subfolders get no shelf of their own.
4. **Loose files** (top level, no folder): titled "Everything else" if any folder shelf or show
   exists, else "On Drop".

`shelf(title, list, fid, layout)` (`:392`) builds a section. The layout is `row` on home and
`grid` in folder views. A grid where every item is audio gets the `audio` class (smaller squares).

## Folder view (`renderFolder(fid)`, `:397-414`)

- Breadcrumbs: `Library / A / B / **Current**`.
- **Chips** for subfolders that contain media somewhere below (`countBelow > 0`), with the count.
  A chip for a show links to `#show=`, the others to `#folder=`.
- If the folder directly holds media: a heading, a **CTA button** (*Play <name>*, or *Continue
  <name>* if started) for the first file that isn't finished and can play here (else the first
  file), then a grid of cards.
- If it holds nothing at all: "Nothing playable in this folder."

## Show page (`renderShow(id, wantSeason)`, `:416-440`)

- `st = showState(sh)`. The visible season is `wantSeason` if the show has it, else the season of
  `st.m` (so the page opens on the season you're in).
- Breadcrumbs: the ancestors as links, then the show name in bold.
- **Header**: the poster (`face` as on the show card), the name, `"N seasons · M episodes"` (N
  without specials, shown only if N > 1), and **one primary button**:

  | `st.mode` | label | plays |
  |---|---|---|
  | `start` | `Play <epLong>` (e.g. "Play E1" or "Play S1 · E1 · The Harbour") | `st.m` (the first playable episode) |
  | `continue` | `Continue <epLong>` | `st.m` |
  | `next` | `Play <epLong>` | `st.m` (the next unfinished episode) |
  | `done` | `Watch again` | `sh.episodes[0]` |

- **Season tabs** only if `sh.seasons.length > 1`. They link to `#show=<id>&s=<n>` and use
  `seasonName` ("Season 2", or "Specials" for 0). Order: the show's watch order, with specials last.
- **Episode rows** for the visible season: a poster with a progress bar, `epShort(m)` (`E2 · Low
  Tide`), and a status (won't play / `x left` / watched / duration). The current `st.m` row gets
  the `now` class (an accent bar) unless the show is done.

Back from the player returns to `#show=<id>&s=<season of the episode>` (see player.md).
