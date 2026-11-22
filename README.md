# Cinema: watch what's on Drop, on every device

An [AirplaneMode](https://github.com/jessewolcott/airplanemode) app. Cinema plays the videos and
music loaded onto [Drop](https://github.com/jessewolcott/airplanemode-drop), on every phone,
tablet and laptop on the hotspot, with no internet.

- **A library from Drop's folders.** Each folder with videos or music becomes a shelf ("Ocean
  Trip", "Kids", "Music"); files sort naturally, so episodes play in order.
- **Posters by themselves.** The first browser to show a video grabs a frame from it and gives
  it to the box, so everyone else sees a poster too.
- **Picks up where you left off, per device.** Every tablet on the plane keeps its own place,
  with a *Continue* shelf. No accounts.
- **Up next.** At the end of an episode the next one in the folder starts after a countdown;
  albums just keep playing. Lock-screen controls (Media Session) on phones.
- **Opens from Drop.** Drop shows *Play in Cinema* on any video or audio file this device can
  play (the platform's `apps.json` declares that Cinema opens `video/*` and `audio/*`).
- **Respects Drop's "downloads off".** The admin can turn downloads off for a file or folder in
  Drop; Cinema still plays it, and hides the browser's download option.

Cinema never touches the media itself: the browser streams straight from Drop (with seeking),
so Cinema needs very little memory (64 MB). Its only data is the posters.

**What plays** depends on the device's browser. MP4 (H.264 + AAC), WebM and MP3/AAC play
everywhere; MKV, HEVC or AC-3 audio may not. Files a device can't play are dimmed and say so.

## Running it

**On the box:** the platform repo runs the released image at `/cinema/`, next to Drop.

**On its own, for development** (with Drop built from `../airplanemode-drop`):

```
docker compose up -d --build        # Cinema http://localhost:8768, Drop http://localhost:8766
python tests/test_cinema.py         # API tests (CI runs these before building)
```

Standalone, Drop is on another port, so the browser treats it as another site and posters
can't be grabbed; everything else works. In the platform's dev stack they share one address.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DROP_URL` | `http://drop:8000` | Drop's API, as this container reaches it |
| `DROP_PATH` | `../drop/` | where the browser streams from (relative to `/cinema/`) |

## API

| | |
|---|---|
| `GET api/library` | Drop's folders and the video/audio files in them, plus `drop_path` |
| `GET api/posters/{id}` | a poster (JPEG/WebP) |
| `PUT api/posters/{id}` | store one; needs `X-Cinema: 1`, max 300 KB, only for files Drop has |

*Not yet tested on real hardware.* Subtitles (`.vtt` next to a video) are a planned addition.
