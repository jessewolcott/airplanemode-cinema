# Per-device memory

Cinema has no accounts and keeps no watch history on the server. Everything personal is in the
browser's `localStorage`, so it's per device and per origin. Every tablet on the plane keeps its
own place.

## Access layer (`static/index.html:200-205`)

```js
const mem = {
  get(k, d = null) { try { const v = localStorage.getItem("cinema." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("cinema." + k, JSON.stringify(v)); } catch {} },
};
const pos = id => mem.get("p." + id);          // {t, d, at}
const savePos = (id, t, d) => { if (d > 0) mem.set("p." + id, { t, d, at: Date.now() }); };
```

Every key is prefixed with `cinema.` and holds JSON. Reads and writes are wrapped in try/catch,
so private mode, a full quota or a blocked storage just means nothing is remembered. The page
still works.

## Keys

| Key | Value | Written by | Read by |
|---|---|---|---|
| `cinema.p.<id>` | `{t: seconds, d: duration, at: epoch ms}` | `savePos`, from the player's `save()`: every 5 s, on pause/ended/pagehide/hidden/close | `started`/`finished`, cards, Continue shelf, `showState` (the most recent `at` = last watched), resume on open |
| `cinema.d.<id>` | duration in seconds (number) | `loadedmetadata` in the player; `grab()` in the poster queue | duration badges on cards, episode rows, the audio track list |
| `cinema.nop.<id>` | `1` | the poster queue, when `grab` fails | the poster queue (skip forever on this device) |

`<id>` is Drop's 16-hex item id. If Drop deletes a file and it's uploaded again, it gets a new id,
so positions don't carry over. Nothing ever prunes old keys. They're tiny.

## In-memory (not persisted)

| Name | What |
|---|---|
| `lib`, `byId`, `folderById` | the last library response, plus indexes |
| `shows` | show id → `{id, name, episodes, seasons}` (rebuilt by `buildShows` on every load) |
| `scrollMem` | hash → `scrollY`, so returning to a view restores its scroll |
| `postering` | poster-queue mutex |
| `media`, `current`, `saveTimer`, `nextTimer`, `idleTimer` | player state |

## Not stored on the server

Positions, history, "watched" state, preferences. The server's only data are poster files. If a
feature needs shared state across devices (e.g. "family profiles"), that's a design change. Write
a platform decision record first (platform `docs/decisions/`).
