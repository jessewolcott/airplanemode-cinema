# Posters

Posters are made **in the browser**, not on the box. The box has no ffmpeg, and decoding video
there would break the 64 MB budget. The first device that shows the library and can play a video
grabs a frame and uploads it. After that, every device gets it from `api/posters/<id>`.

## The queue (`posterQueue()`, `static/index.html:534-553`)

It runs after every `load()` (the first load and each 30 s refresh). A module flag `postering`
keeps only one queue running.

For each item in `lib.media`, in Drop's order (newest first), it skips the item if:

- `m.poster` is already true (the server has one);
- it isn't a video (audio gets a note placeholder, never a poster);
- `!playable(m)` (this browser can't decode it, so it can't grab a frame either);
- `mem nop.<id>` is set: this device already failed on it (see below).

Then:

1. **It never competes with playback**: `while (player is open) await 3 s`. The queue pauses as
   soon as someone starts watching and resumes when they leave the player.
2. `grab(m)` → a JPEG `Blob`, or `null` on failure.
3. On failure, set `mem nop.<id> = 1` and move on. That device never tries that file again (the
   flag is permanent in `localStorage`). Other devices still can.
4. `PUT api/posters/<id>` with headers `X-Cinema: 1` and `Content-Type: blob.type`, and the blob as
   body. Network errors are swallowed.
5. On a 2xx response: set `m.poster = true` and patch the DOM in place. For every
   `a.card[href="#play=<id>"] .poster` it clears the placeholder icon and inserts
   `<img src="api/posters/<id>?v=1">`. The `?v=1` gets around any cached 404 for the plain URL
   (posters are served with a 1-day private cache). Show cards and episode rows aren't patched;
   they pick the poster up on the next render (the 30 s refresh or navigation).

## Grabbing a frame (`grab(m)`, `:554-575`)

```
v = <video>; muted, playsInline, preload="metadata", crossOrigin="anonymous"
timeout 20 s → fail
onloadedmetadata: mem d.<id> = duration; seek to clamp(duration × 0.12, 1 s, 300 s)
onseeked: draw onto a 480×270 canvas with a 16:9 cover-crop → toBlob("image/jpeg", 0.74)
v.src = src(m)        // straight from Drop, like playback
```

- **Seek target**: 12% in skips black openings and studio logos, at least 1 s, at most 5 min (so
  long films don't seek deep into the file).
- **Cover-crop** (`:566-569`): the source aspect is `r = videoWidth / videoHeight` (16:9 if
  unknown). If wider than 16:9, crop the sides (`sw = sh·16/9`, centred). Otherwise crop the top
  and bottom (`sh = sw·9/16`, centred). Then `drawImage(v, sx, sy, sw, sh, 0, 0, 480, 270)`, so
  portrait phone videos and 4:3 footage both fill the 16:9 card without letterboxing.
- **Output**: a JPEG at quality 0.74, 480×270. That's usually tens of KB, well under the server's
  300 KB limit. The server also accepts WebP, but the client never sends it.
- **Cleanup** in every path: clear the timer, remove `src` and call `load()` to release the
  connection to Drop.
- Grabbing also caches the duration, which is why cards get duration badges before anyone has
  watched them.

### Why `crossOrigin = "anonymous"`, and why standalone dev has no posters

A canvas that has drawn a cross-origin video without CORS approval is *tainted*, and `toBlob`
throws a `SecurityError`. On the box, Drop is the same origin (`/drop/` behind the same Caddy),
so the frame is readable. In this repo's standalone `compose.yaml`, Drop is
`http://localhost:8766` and Cinema `:8768`, so they're different origins. Drop sends no CORS
headers, so with `crossOrigin="anonymous"` the video either fails to load (`onerror`) or taints
the canvas (the `catch`). Either way `grab` rejects, the device sets `nop.<id>` and moves on: "no
posters, no harm" (the comment at `:571`). Test posters in the **platform dev stack** instead.

Side effect: running standalone sets `nop.*` flags in that origin's `localStorage`
(`localhost:8768`). They don't affect the platform stack (`localhost:8080`, a different origin).
Clear site data to retry.

## Server side (summary; see backend.md)

- `PUT` needs `X-Cinema: 1`, a 16-hex id **that Drop currently lists as media** (an id cache
  refreshed every 60 s), ≤ 300 KB (checked while streaming), and JPEG/WebP magic bytes. There's a
  5000-file cap for new posters. The write is atomic (tmp + replace).
- `GET` sniffs WebP vs JPEG from the bytes; `nosniff`; `private, max-age=86400`.
- `api/library` reports `poster: true|false` per media item and **deletes posters whose file is
  gone from Drop** on every call.

## Where posters show up

Cards (lazy `<img>` that fades in), show cards and the show header (the current episode's poster,
else any episode's), episode rows, the up-next card background, and Media Session artwork.
