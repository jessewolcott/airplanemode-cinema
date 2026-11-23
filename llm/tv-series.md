# TV series

All of this is in `static/index.html` between `const nat =` (`:167`) and `// ---- library ----`
(`:278`). `tests/test_series.mjs` executes **exactly that slice** under Node (see
testing-and-release.md), so:

- keep the series code inside those markers;
- don't touch the DOM, `$` or `esc` **at load time** in that slice (functions that use the DOM
  when called are fine; `playable()` calls `document.createElement`, which the test stubs);
- don't rename the two marker strings without updating the test.

## Model

A **show** is a Drop folder. Its media (at any depth below it) are **episodes**, and its
subfolders are **seasons**, never shelves. `buildShows()` mutates each episode's media object:

| field | meaning |
|---|---|
| `m.show` | the show's folder id (absent for non-episodes) |
| `m.season` | season number; `0` = specials |
| `m.ep` | episode number, or `null` |
| `m.epTitle` | text after the episode marker in the file name, or `null` |

`shows` is a `Map` of folder id → `{id, name, episodes, seasons}`. `episodes` are in watch order;
`seasons` lists the distinct season numbers in that order (specials last).

## `parseEp(name)` (`:201-218`)

The name is first normalized: drop the extension (`\.[a-z0-9]{2,5}$`), then turn every run of
`.`/`_` into a space. The patterns are tried **in order**, and the first match wins:

| # | Regex | Gives | Example |
|---|---|---|---|
| 1 | `\bS(\d{1,2})[ ._-]*E(\d{1,3})\b` (case-insensitive) | season, ep | `S01E02`, `s2e10`, `S1 E3`, `S01-E04` |
| 2 | `\b(\d{1,2})x(\d{2,3})\b` (case-insensitive) | season, ep | `1x03` (the episode needs ≥ 2 digits, so `1x3` doesn't match) |
| 3 | `\b(?:episode\|ep)[ ._-]*(\d{1,3})\b` (case-insensitive) | ep only | `Episode 4`, `ep_12` (`_` became a space), `Ep 2` |
| 4 | `\bE(\d{1,3})\b` (**case-sensitive**, capital E) | ep only | `Night Ferry E01` |

The **title** is whatever follows the match, with leading spaces, `-`, `–`, `—` and `:` trimmed
and inner spaces collapsed, or `null` if nothing follows. Text *before* the match (usually the
show name) is discarded.

Returns `{season, ep, title}` or `null`. From the tests:

```
"Coastal.Life.S01E02.Low.Tide.mp4"     → {season: 1, ep: 2, title: "Low Tide"}
"Show - s2e10.mkv"                     → {season: 2, ep: 10, title: null}
"Coastal Life 1x03 - Storm Season.mp4" → {season: 1, ep: 3, title: "Storm Season"}
"Episode 4 - New Shores.mp4"           → {season: null, ep: 4, title: "New Shores"}
"ep_12.mp4"                            → {season: null, ep: 12, title: null}
"Holiday 2024.mp4"                     → null   (a year isn't an episode)
"1080p sunset.mp4"                     → null
```

Deliberately not matched: a bare number ("03 - Title.mp4"), resolutions, years. Pattern 4 being
case-sensitive keeps words like "e1" inside other tokens from counting, though `\b` already guards
most of that.

## `seasonOf(folderName)` (`:219-224`)

- `^(specials?|extras?)$` (case-insensitive) → `0`.
- Else `^(?:season|series|staffel|saison|temporada|s)?[ ._-]*(\d{1,2})$`, anchored: an optional
  word, then a 1-2 digit number and nothing else. Matches "Season 1", "season_02", "S3",
  "Series 4", "Staffel 2", and a bare "5".
- Else `\b(?:season|series)[ ._-]*(\d{1,2})\b` anywhere, e.g. "Show Season 6 (2019)" → 6.
- Else `null` ("Kids", "Movies", "Beach 2024"; 4 digits don't count).

## `isShow(folder)` (`:226-230`)

A folder is a show if **either**:

- it has at least one *season-like child*: a subfolder that has media somewhere below it
  (`countBelow > 0`) **and** either has a season name (`seasonOf !== null`) or directly contains
  a file that `parseEp` understands; **or**
- it directly contains **at least 2** files that `parseEp` understands.

So "Movies/Kids" (no episode names) stays an ordinary shelf. A single `S01E01.mp4` in a folder
doesn't make it a show. In the test library, "TV/Night Ferry/{Part A, Part B}/Night Ferry E0x.mp4"
makes **Night Ferry** a show (its subfolders contain episode files), but not **TV**: TV's only
child "Night Ferry" has no season name and no episode files directly inside it.

## `buildShows()` (`:231-240`)

It resets `shows` and deletes `m.show` from every item, then walks the folder tree from the top
(`walk(null)`) in natural order. For each subfolder: if `isShow(f)` → `addShow(f)` and **don't
descend** (shows can't nest, and a show's subfolders are seasons). Otherwise recurse. Loose
top-level files are never part of a show (the root isn't a folder).

## `addShow(f)`: season assignment and order (`:241-257`)

```js
collect(fid, season, idx):
  for each media m directly in fid:
    e = parseEp(m.name) || {}
    m.season = season ?? e.season ?? idx ?? 1
    m.ep = e.ep ?? null; m.epTitle = e.title ?? null; m.show = f.id
  for each subfolder k (natural order, index i):
    collect(k, season ?? seasonOf(k.name) ?? null,      // explicit season, inherited downward
               season ?? seasonOf(k.name) ?? i + 1)     // fallback: position among siblings
collect(f.id, null, null)
```

Priority for an episode's season:

1. **The season folder's name** (or an ancestor season folder's name, inherited). This even
   overrides the file name: `S02E01.mp4` inside "Season 1" counts as season 1.
2. **The file name** (`S01E02`, `1x02`).
3. **The folder's position** among its siblings in natural order (1-based). This is why "Part A"
   and "Part B" become seasons 1 and 2.
4. **`1`** for files directly in the show folder with no season in their name.

`??` keeps `0`, so "Specials" (season 0) propagates correctly.

**Sort** (`:253-254`): by season, with `0` mapped to 999 (specials last); then by episode number
(`null` → 1e6, so unnumbered files go after the numbered ones in a season); then `nat` by file
name. `seasons = [...new Set(episodes.map(m => m.season))]`, which is therefore in watch order.

Worked example (from the test):

```
Coastal Life/
  Season 2/  Episode 2.mp4, Episode 1 - New Shores.mp4
  Season 1/  Coastal.Life.S01E02.Low.Tide.mp4, …S01E01.The.Harbour.mp4, Coastal Life 1x03 - Storm Season.mp4
  Specials/  Behind the Scenes.mp4
→ episodes [S1E1, S1E2, S1E3, S2E1, S2E2, S0(null)]; seasons [1, 2, 0]
```

## Labels (`:258-267`)

- `seasonName(n)`: "Specials" for 0, else "Season n".
- `epShort(m)`: `E<ep> · <epTitle>`, or `E<ep>`. Without an episode number: `epTitle`, or else
  `tidy(m.name)`. E.g. "E1 · New Shores", and "Behind the Scenes" for a special.
- `epLong(m)`: prefixes `S<n> · ` (or `Special · ` for season 0) **only if** the show has more
  than one season **or** `m.season > 1`. So a one-season show says "E2", not "S1 · E2".
  E.g. "S1 · E2 · Low Tide", "Special · Behind the Scenes".
- `titleOf(m)`: `epLong(m)` for episodes, `tidy(m.name)` for everything else ("Whale Song").

## `showState(sh)`: what to watch next (`:269-276`)

It uses this device's saved positions (`pos(id)`, see player.md for `finished`):

1. Nothing in the show has a saved position → `{mode: "start", m: first playable episode
   (or the first), at: 0}`.
2. Otherwise take the episode with the most recent `at` (last touched):
   - not `finished` → `{mode: "continue", m: that episode}`. Note: any saved position counts,
     even a few seconds. The player only seeks back if `started()` is true, though.
   - finished → the first episode **after it** in watch order that isn't finished → `{mode:
     "next"}`. It crosses seasons (S1E3 → S2E1). Unfinished episodes *before* it are ignored.
   - none left → `{mode: "done", m: the last-watched episode}`.

`at` is carried through for sorting the Continue shelf. Consumers: the home Continue shelf (only
`continue`/`next`), `showCard`, `renderShow`. The test walks through start → continue → next →
next across seasons → done.

## How the player uses shows

When an episode plays, the playlist is `sh.episodes` (the **whole show** in watch order), not its
folder. So *Up next* and the lock-screen next/previous buttons carry on across seasons, and the
up-next card says "Up next · Season 2" when it crosses one. Back returns to
`#show=<id>&s=<season>`. See player.md.
