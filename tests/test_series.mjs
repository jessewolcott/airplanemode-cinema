// Tests for the page's TV-series logic (episode parsing, show detection, watch order, "what's next").
// Runs the code straight out of static/index.html, so there's nothing to keep in sync.
//   node tests/test_series.mjs
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
const start = html.indexOf("const nat =");
const end = html.indexOf("// ---- library ----");
assert.ok(start > 0 && end > start, "couldn't find the series code in index.html");

const store = new Map();
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
globalThis.document = { createElement: () => ({ canPlayType: () => "probably" }) };

const api = new Function(`${html.slice(start, end)}
  return { parseEp, seasonOf, buildShows, showState, epLong, epShort, titleOf, savePos, partyPos, syncStep, ownEvent, clockOffset,
           setLib: l => { lib = l; byId = new Map(l.media.map(m => [m.id, m])); folderById = new Map(l.folders.map(f => [f.id, f])); },
           shows: () => shows };`)();

let n = 0;
const test = (name, fn) => { fn(); n++; console.log("ok  ", name); };

test("episode numbers from file names", () => {
  assert.deepEqual(api.parseEp("Coastal.Life.S01E02.Low.Tide.mp4"), { season: 1, ep: 2, title: "Low Tide" });
  assert.deepEqual(api.parseEp("Show - s2e10.mkv"), { season: 2, ep: 10, title: null });
  assert.deepEqual(api.parseEp("Coastal Life 1x03 - Storm Season.mp4"), { season: 1, ep: 3, title: "Storm Season" });
  assert.deepEqual(api.parseEp("Episode 4 - New Shores.mp4"), { season: null, ep: 4, title: "New Shores" });
  assert.deepEqual(api.parseEp("ep_12.mp4"), { season: null, ep: 12, title: null });
  assert.equal(api.parseEp("Holiday 2024.mp4"), null);           // a year isn't an episode
  assert.equal(api.parseEp("1080p sunset.mp4"), null);
});

test("season numbers from folder names", () => {
  for (const [name, s] of [["Season 1", 1], ["season_02", 2], ["S3", 3], ["Series 4", 4], ["5", 5], ["Staffel 2", 2], ["Specials", 0], ["Extras", 0], ["Show Season 6 (2019)", 6]])
    assert.equal(api.seasonOf(name), s, name);
  for (const name of ["Kids", "Movies", "Beach 2024"]) assert.equal(api.seasonOf(name), null, name);
});

const id = (n) => n.toString(16).padStart(16, "0");
const F = (i, name, parent = null) => ({ id: id(i), name, parent: parent && id(parent) });
const M = (i, name, parent, kind = "video") => ({ id: id(100 + i), name, parent: parent && id(parent), kind, type: kind === "video" ? "video/mp4" : "audio/mpeg" });
const lib = {
  drop_path: "../drop/",
  folders: [
    F(1, "Coastal Life"), F(2, "Season 2", 1), F(3, "Season 1", 1), F(4, "Specials", 1),
    F(5, "Movies"), F(6, "Kids", 5),
    F(7, "Ocean Trip"),
    F(8, "TV"), F(9, "Night Ferry", 8), F(10, "Part A", 9), F(11, "Part B", 9),
  ],
  media: [
    M(1, "Coastal.Life.S01E02.Low.Tide.mp4", 3), M(2, "Coastal.Life.S01E01.The.Harbour.mp4", 3), M(3, "Coastal Life 1x03 - Storm Season.mp4", 3),
    M(4, "Episode 2.mp4", 2), M(5, "Episode 1 - New Shores.mp4", 2),
    M(6, "Behind the Scenes.mp4", 4),
    M(7, "Whale Song.mp4", 6), M(8, "Lighthouse Keeper.mp4", 5),
    M(9, "Ocean.Trip.S01E01.mp4", 7), M(10, "Ocean.Trip.S01E02.mp4", 7),
    M(11, "Night Ferry E01.mp4", 10), M(12, "Night Ferry E02.mp4", 10), M(13, "Night Ferry E01.mp4", 11),
  ],
};

test("which folders are shows", () => {
  api.setLib(lib);
  api.buildShows();
  const names = [...api.shows().values()].map(s => s.name).sort();
  assert.deepEqual(names, ["Coastal Life", "Night Ferry", "Ocean Trip"]);   // not Movies/Kids, not TV, not seasons
});

test("episodes in watch order across seasons, specials last", () => {
  const sh = api.shows().get(id(1));
  assert.deepEqual(sh.episodes.map(m => [m.season, m.ep]), [[1, 1], [1, 2], [1, 3], [2, 1], [2, 2], [0, null]]);
  assert.deepEqual(sh.seasons, [1, 2, 0]);
  assert.equal(api.epLong(sh.episodes[1]), "S1 · E2 · Low Tide");
  assert.equal(api.epShort(sh.episodes[3]), "E1 · New Shores");
  assert.equal(api.epLong(sh.episodes[5]), "Special · Behind the Scenes");
  // season folders without season names count in folder order
  const nf = api.shows().get(id(9));
  assert.deepEqual(nf.episodes.map(m => [m.season, m.ep]), [[1, 1], [1, 2], [2, 1]]);
  // a one-season show doesn't say "S1"
  assert.equal(api.epLong(api.shows().get(id(7)).episodes[1]), "E2");
  // films stay films
  assert.equal(api.titleOf(lib.media.find(m => m.name === "Whale Song.mp4")), "Whale Song");
});

test("what to watch next in a show", () => {
  const sh = api.shows().get(id(1)), ep = sh.episodes;
  assert.deepEqual([api.showState(sh).mode, api.showState(sh).m], ["start", ep[0]]);
  api.savePos(ep[0].id, 300, 1500);                                    // halfway through S1E1
  assert.deepEqual([api.showState(sh).mode, api.showState(sh).m], ["continue", ep[0]]);
  api.savePos(ep[0].id, 1499, 1500);                                   // finished it
  assert.deepEqual([api.showState(sh).mode, api.showState(sh).m], ["next", ep[1]]);
  for (const e of ep.slice(1, 3)) api.savePos(e.id, 1499, 1500);     // finish season 1
  assert.deepEqual([api.showState(sh).mode, api.showState(sh).m], ["next", ep[3]]);   // carries into season 2
  for (const e of ep.slice(3)) api.savePos(e.id, 1499, 1500);
  assert.equal(api.showState(sh).mode, "done");
});



// ---- Sync Watch decisions ----
test("party position runs on while playing, stands still while paused", () => {
  assert.equal(api.partyPos({ playing: true, pos: 10, at: 1000 }, 3500), 12.5);
  assert.equal(api.partyPos({ playing: false, pos: 10, at: 1000 }, 3500), 10);
  assert.equal(api.partyPos({ playing: true, pos: 10, at: 5000 }, 3500), 10);   // a clock behind the box: never backwards
});

test("following the party: nudge small drift, jump big drift, mirror play/pause", () => {
  const st = { playing: true, pos: 100, at: 0 }, at = t => ({ t, paused: false, ended: false });
  assert.deepEqual(api.syncStep(st, 0, at(100.03)), { pause: false, play: false, seek: null, rate: 1 });   // in step
  const behind = api.syncStep(st, 0, at(99.6));
  assert.ok(behind.seek === null && behind.rate > 1 && behind.rate <= 1.1, JSON.stringify(behind));        // catch up
  const ahead = api.syncStep(st, 0, at(100.4));
  assert.ok(ahead.seek === null && ahead.rate < 1 && ahead.rate >= 0.9, JSON.stringify(ahead));           // ease off
  assert.equal(api.syncStep(st, 0, at(90)).rate, 1);
  assert.equal(api.syncStep(st, 0, at(90)).seek, 100);                                                    // far off: jump
  assert.equal(api.syncStep(st, 0, at(98.5)).seek, 100);
  assert.equal(api.syncStep(st, 0, { t: 100, paused: true, ended: false }).play, true);                    // they play: we play
  assert.equal(api.syncStep(st, 0, { t: 100, paused: true, ended: true }).play, false);                    // but not a finished file
  const paused = { playing: false, pos: 50, at: 0 };
  assert.deepEqual(api.syncStep(paused, 9e9, at(50.1)), { pause: true, play: false, seek: null, rate: 1 }); // they pause: we pause
  assert.equal(api.syncStep(paused, 0, { t: 60, paused: true, ended: false }).seek, 50);                   // and stand where they stand
});

test("only the person's own actions go to the party, not our corrections", () => {
  const playing = { playing: true, pos: 100, at: 0 }, paused = { playing: false, pos: 100, at: 0 };
  const loc = (t, ended = false) => ({ t, paused: false, ended });
  assert.equal(api.ownEvent("play", playing, 0, loc(100)), true);      // we started it to follow the party
  assert.equal(api.ownEvent("play", paused, 0, loc(100)), false);      // the person pressed play
  assert.equal(api.ownEvent("pause", paused, 0, loc(100)), true);
  assert.equal(api.ownEvent("pause", playing, 0, loc(100)), false);    // the person paused
  assert.equal(api.ownEvent("pause", playing, 0, loc(100, true)), true); // the file ended: not a pause for everyone
  assert.equal(api.ownEvent("seeking", playing, 0, loc(100.5)), true);  // our own jump
  assert.equal(api.ownEvent("seeking", playing, 0, loc(400)), false);   // the person skipped
});

test("clock offset comes from the quickest round trip", () => {
  assert.equal(api.clockOffset([{ rtt: 80, offset: 500 }, { rtt: 12, offset: 230 }, { rtt: 40, offset: 260 }]), 230);
});

console.log(`${n} passed`);
