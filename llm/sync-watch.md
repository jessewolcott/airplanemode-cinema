# Sync Watch (watch parties)

Several phones play the same file in step, each with its own sound (earbuds), each streaming
from Drop itself. Cinema still never touches media bytes: the box only keeps a few numbers per
party. Platform decision 0023.

## What the box keeps (`app.py`)

`Party(Room)` subclasses `amrooms.Room` (the platform's Rooms SDK, `../airplanemode/sdk/rooms`):
seats, seat tokens, who's who names, presence and long-poll come from there. A party adds:

- `item`: the Drop file id; `playing_now`: bool; `pos`: seconds; `at`: ms on the box's wall
  clock (`now_ms()`, `time.time() * 1000`) when `pos` was true. Position now =
  `pos + (now - at) / 1000` while playing (`Party.position`).
- `apply(i, kind, pos, item)`: `play` / `pause` (set `pos` from the request, or from
  `position()` if absent, and `playing_now`), `seek` (keeps play/pause), `item` (new file at 0,
  playing; the same item again does nothing, because every phone's "up next" fires at once).
  Sets `at = now`, `last = {by, type}`, `changed()`.
- `empty()` is overridden: a party is over when nobody has polled for `GONE_AFTER` (600 s), so
  a phone that locked mid-film can come back. The registry `parties = Rooms(Party,
  max_rooms=50, idle=6 h, empty_grace=30)` sweeps every 5 s (lifespan).
- `summary()` (the library shelf) counts only people who aren't away as `watching`.
- No game, no bots, no driver: people join and leave any time (`game` stays None, so the SDK
  treats every party as a lobby: joinable, listed if public, evictable at the cap).

Routes (POSTs need `X-Cinema: 1`; the seat token goes in `X-Seat`):

| Route | Does |
|---|---|
| `GET api/watch` | open parties: `{code, item, playing, host, avatar, watching}` |
| `GET api/watch/clock` | `{now}`: the box's clock in ms |
| `POST api/watch {item, pos, playing}` | `drop_has(item)` or 404; `seconds(pos)` (number, finite, 0..7 days) or 400; `whois()`; create + join -> `{code, token, state}` |
| `POST api/watch/{code}/join {token?}` | SDK `join`: your seat back by token or who's who, else a new one |
| `GET api/watch/{code}/state?since=N` | 403 without a seat; long-poll (`CINEMA_POLL_WAIT`, default 20 s); 404 once the party or your seat is gone |
| `POST api/watch/{code}/act {type, pos?, item?}` | `item` must be on Drop (404); unknown type 400 |
| `POST api/watch/{code}/leave` | SDK `leave` (the seat goes), then a sweep (the last one out ends it) |

`drop_has(id)` re-reads Drop's list at most once a minute, or on a miss after 5 s.
Parties live in memory: restarting Cinema ends them all.

## What each phone does (`static/index.html`)

Pure decisions, in the slice `tests/test_series.mjs` runs (between `const nat =` and
`// ---- library ----`):

- `partyPos(st, now)`: where the party is (never runs backwards on a clock behind the box).
- `syncStep(st, now, local)`: paused party -> pause, and seek if more than 0.3 s off; playing
  party -> play if paused (not if this file ended), seek if more than 1 s off, otherwise
  `playbackRate = 1 + clamp(diff * 0.5, ±0.1)` with a 0.08 s dead band (browsers keep pitch).
- `ownEvent(kind, st, now, local)`: was a player event caused by us following the party? `play`
  while the party plays, `pause` while it's paused or at the end of the file, `seeking` to
  within 1.5 s of the party's position. Anything else is the person, and goes to the party.
- `clockOffset(samples)`: the offset from the round trip with the shortest time.

The rest (section `// ---- Sync Watch: watch parties`):

- `party = {code, token, st, offset, gen, ctl}`; saved as `cinema.party` in localStorage so a
  refresh in the player rejoins (`load()` -> `joinParty`).
- `measureClock()`: five `GET api/watch/clock` round trips at join.
- `pollParty(gen)`: long-poll loop, aborted by `leaveParty` (`ctl`); 403/404 ends the party.
- `applyParty(st)`: ignores older versions; a note ("Sam paused") for someone else's action
  (`st.at` moved and `last.by` isn't you); `followItem` (another file: go there, loading the
  library first if Drop has something new) or `syncNow`.
- `syncNow()` every 500 ms and on `loadedmetadata`; skips when this file ended and the party
  plays (up next moves everyone on).
- `tellParty` on `play` / `pause` / `seeking` (not `seeked`: the 500 ms loop would pull a
  person's seek back before it finished). `partyAct` updates `party.st` optimistically so the
  events it causes aren't sent back.
- In a party the player doesn't autoplay (joining a paused party must not unpause it);
  `syncNow` starts playback, and if the browser refuses (iOS without a tap) shows "Tap to join in".
- `openPlayer` for a different file than the party's sends `item` (next episode, a track, a card).
- Leaving the player (back, the library) leaves the party; back asks first if others are there.
  The home button leaves too. Closing the page doesn't (the seat goes away after 10 minutes).
- The library's first shelf, "Watching together", is `partyList` (`loadParties`, every 8 s
  while the library shows); its cards link to `#watch=<code>`.

## Limits and untested

- Each phone streams its own copy from Drop: N phones = N streams of one file. How many the
  R6S's Wi-Fi and eMMC carry at once is *untested* (`../airplanemode/docs/testing.md`).
- Nobody waits for a phone that's buffering: it falls behind and jumps to catch up.
- Measured in the dev stack (two desktop Chromium contexts on one laptop): within 0.1 s after
  joining and after every action. Real phones over Wi-Fi are *untested*.
