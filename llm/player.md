# The player

`static/index.html:457-560`. The player is a fixed full-screen overlay (`#player`) containing a
top bar (`.pbar`: back button, title and subtitle, and the AirplaneMode home button
`a.am-home` at the right end) and a `#stage`. It opens on `#play=<id>`
through `route()` → `openPlayer(m)`.

Module state: `media` (the `<video>`/`<audio>` element), `current` (the media item), and
`saveTimer`, `nextTimer`, `idleTimer`.

## `openPlayer(m)` step by step (`:459-507`)

1. `closePlayer(true)` tears down any previous media (saving its position first) but keeps the
   player view visible, so going episode to episode doesn't flash the library.
2. `document.title` becomes `"<Show> · <epLong> · Cinema"` or `"<tidy name> · Cinema"`. The bar
   shows the show name with `epLong` underneath, or the file name with the folder label (or
   "Drop").
3. **Playlist**: `list = sh ? sh.episodes : inFolder(m.parent)`, with `idx = list.indexOf(m)`. For
   a show, it's the whole show across seasons. Otherwise it's the files in the same folder (for
   top-level files, all loose top-level media), in natural order, mixing audio and video if the
   folder does.
4. **`download: false`** (Drop's "downloads off"): the media element gets
   `controlslist="nodownload"` and `oncontextmenu="return false"`. That hides the browser's
   download menu item and the right-click "Save video as". It's a courtesy, not protection: the
   stream URL still works, by design (decision 0013).
5. **Video**: `#stage.stage` with `<video id="media" controls autoplay playsinline preload="auto">`.
   `playsinline` keeps iOS from forcing full screen.
6. **Audio**: `#stage.audio` holds a square gradient "album art" (from the folder label or name)
   with a note icon, the title (`titleOf`), a subtitle (show or folder, plus "i of n"), an
   `<audio controls autoplay preload="auto">`, and if the playlist has more than one item, a
   **track list** of buttons (number, or ▶ for the current one; title; cached duration). Clicking
   a track does `go("play=<id>")`.
7. If `!playable(m)`, a note explains the device's browser may not play this type, and suggests
   MP4 (H.264) or MP3. Playback is attempted anyway.
8. `media.src = src(m)`, so it streams from Drop directly.
9. Event wiring (below), `saveTimer = setInterval(save, 5000)`, then `media.play?.().catch(() => {})`.
   Autoplay with sound may be refused (iOS); the native controls are still there.
10. Media Session setup, then `armIdle()`.

## Resume and progress

- On `loadedmetadata` (once): it stores the duration as `mem d.<id>` (used by card badges and the
  track list). If the saved position `p` is `started(p)`, it seeks to `p.t` and shows a toast
  **"Picked up at m:ss"** with a **Start over** button (sets `currentTime = 0`).
- `save()` (`:508`): if there's media with a duration → `savePos(current.id, currentTime,
  duration)`, which writes `cinema.p.<id> = {t, d, at: Date.now()}`. `savePos` ignores `d <= 0`.
- It's called every **5 s** (`saveTimer`), on `pause`, on `ended`, on `pagehide`, when the page
  goes hidden (`visibilitychange`), and in `closePlayer`. So locking the phone or switching tabs
  keeps the place.

## Finished and started (`:206-208`)

```js
// the last 25 s of a film are credits; a short clip isn't finished until it nearly is
const finished = p => p && p.d && (p.t / p.d > 0.95 || (p.d > 300 && p.d - p.t < 25));
const started  = p => p && p.d && p.t > Math.min(15, p.d * 0.1) && !finished(p);
```

- **Finished**: past 95% of the way, **or**, for anything longer than 5 minutes, within the last
  25 s (credits). The `p.d > 300` guard is the **short-clip fix**: without it, any clip shorter
  than 25 s would count as finished the moment it started (and a 40 s clip after 15 s).
- **Started** (shows a progress bar, offers resume, appears in Continue): past 15 s, or past 10%
  for clips shorter than 150 s, and not finished. So briefly opening a file doesn't put it in
  Continue.
- Both are falsy when there's no position.

## Toasts (`toast(text, label, fn)`, `:524-531`)

There's one toast at a time (an existing one is removed). It's a pill at the bottom with a button
that runs `fn`, and it disappears after 7 s. It's used for resume ("Start over") and for errors.

## Errors

On the media element's `error` event: the toast "This file won't play here." with **Back**
(`history.back()` if there's history, else home).

## Up next (`upNext(n)`, `:532-545`)

On `ended`: `save()`, then `upNext(list[idx + 1])`.

- No next item, or the next one isn't `playable` → nothing happens. It doesn't skip ahead to a
  later playable file.
- **Audio** next → `go("play=<id>")` immediately, so albums play straight through.
- **Video** next → a card in the bottom right with the next poster (or a gradient), an **8 s
  countdown** ring, "Up next" (plus " · Season N" / " · Specials" when the next episode is in
  another season), the title, and **Cancel** / **Play** buttons. When it reaches 0 →
  `go("play=<id>")`.
- `hideNext()` clears the timer and removes the card. It runs on Cancel and on the media's
  `play` event (e.g. the user scrubs back and plays again).

## Back button and Escape (`:516-520`)

- Episode → `#show=<show>&s=<season>`.
- Otherwise → `#folder=<parent>`, or home for loose files.

It navigates rather than calling `history.back()`, so it works the same when the player was
opened directly from a Drop link.

## `closePlayer(keepView)` (`:509-515`)

It saves the position, pauses, **removes `src` and calls `load()`**. That makes the browser drop
the HTTP connection to Drop instead of buffering on in the background. It then clears all timers,
nulls `media`/`current` and empties the stage. Unless `keepView` is set, it hides the player,
shows the library and resets the title. `route()` calls it for every non-play route, which makes
the browser's Back button a full stop.

## Media Session (`:500-505`)

If supported (lock screen and notification controls on phones):

- metadata: `title: titleOf(m)`, `artist`: the show name, folder label or "AirplaneMode",
  `album: "Cinema"`, plus artwork from `api/posters/<id>` (declared as `480x270`, `image/jpeg`) if
  there's a poster;
- the `nexttrack` / `previoustrack` handlers play `list[idx ± 1]`, or are set to `null` at the
  ends of the list. For shows, that follows the whole show across seasons.

## Keyboard (`:551-560`)

Active only while `media` exists, and ignored when the focus is in an input or textarea:

| Key | Action |
|---|---|
| Space, `k` | play/pause (default prevented) |
| → , `l` | +10 s (clamped to the duration) |
| ← , `j` | −10 s (clamped to 0) |
| `f` | toggle full screen on the media element |
| `m` | mute/unmute |
| Escape | back (only when not full screen, where Escape exits full screen instead) |

## Idle UI (`:546-550`)

`armIdle()` removes `.idle` and, for **video only**, starts a 2.5 s timer that adds `.idle` to
`#player` if the video is still playing. `.idle` fades out the top bar's gradient (`.pbar::before`)
and every child except `a.am-home`, which stays at 60% opacity and clickable (the platform's app
contract: the home button is on every screen, the player included). The bar itself gets
`pointer-events: none` while idle; the home button turns them back on. It's re-armed
on `mousemove`, `touchstart` and `keydown` over the player, and on play/pause. Audio never goes
idle.

## Leaving with the home button

`a.am-home` (`href="../"`) leaves without asking: `pagehide` saves the position, and the next
visit resumes it, so nothing is lost. Native full screen shows only the video, so the button
is hidden there until full screen ends (the browser's own UI, not ours).

## Interaction with the rest of the page

- While the player is open, the 30 s library refresh is skipped and the poster queue waits, so
  playback has the network to itself.
- The player view and the library are siblings. The library DOM stays in place, hidden, which
  keeps its scroll position.
