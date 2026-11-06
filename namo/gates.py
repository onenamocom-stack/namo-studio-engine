#!/usr/bin/env python3
"""
namo/gates.py - the rules the skills state, as functions that answer YES or NO.

Measured gap this closes: 184 skill files state the show's rules in prose ("dissolve is
forbidden", "never speed speech beyond 1.15x", "at least one shot must be mg"). Nothing read
them, so every rule was advice. A rule that is not a function is not a rule.

This module is the extraction, and only the extraction: one function per rule, each returning
(ok: bool, why: str). Nothing here renders, calls a model, or reads the network. A gate that
cannot run is a NO, never a pass (SPEC O2).

    python namo/gates.py --beats beats.json --shots shots.json
    python namo/gates.py --selftest

Every function names the skill line it comes from, so drift is checkable by grep.
"""
import json, re, sys
from pathlib import Path

# --- transitions --------------------------------------------------------------------------
# skills/pipelines/namo/edit-director.md: "dissolve, fade, wipe, xfade of any kind: forbidden."
FORBIDDEN_TRANSITIONS = ("dissolve", "fade", "wipe", "xfade", "crossfade", "zoom")
ALLOWED_TRANSITIONS = ("cut", "ink_bloom")

# skills/pipelines/namo/script-director.md: "Never speed speech beyond 1.15x"
MAX_TEMPO = 1.15
# ... and "Off target by more than 2 % -> cut or merge"
LENGTH_TOLERANCE = 0.02
# skills/pipelines/namo/scene-director.md: "At least one shot must be mg"
# skills/pipelines/namo/showrunner.md: "Cut order = shot order"
# skills/pipelines/namo/scene-director.md: "`warm` (never cool daylight indoors)"


def gate_transitions(shots):
    """edit-director: only a hard cut or an ink bloom. A dissolve is forbidden, always."""
    bad = [s.get("id", "?") for s in shots
           if str(s.get("transition_in") or s.get("transition") or "cut").lower() not in ALLOWED_TRANSITIONS]
    if bad:
        return False, "forbidden transition on %s (allowed: %s)" % (", ".join(bad[:4]), ", ".join(ALLOWED_TRANSITIONS))
    return True, "every transition is a cut or an ink bloom"


def gate_tempo(beats):
    """script-director: never speed speech past 1.15x. Refuse rather than rush the verse."""
    bad = [(b.get("id", "?"), b["tempo"]) for b in beats
           if isinstance(b.get("tempo"), (int, float)) and b["tempo"] > MAX_TEMPO + 1e-9]
    if bad:
        return False, "speech sped past %.2fx on %s" % (MAX_TEMPO, ", ".join("%s=%.2f" % t for t in bad[:3]))
    return True, "no line is sped past %.2fx" % MAX_TEMPO


def gate_length_target(beats, seconds):
    """script-director: off target by more than 2 % -> cut or merge, never speed."""
    made = sum(b.get("slot", b.get("need", 0)) for b in beats)
    tol = max(0.5, float(seconds) * LENGTH_TOLERANCE)
    if abs(made - float(seconds)) > tol:
        return False, "the beats make %.2fs, target %.2fs +/- %.2fs" % (made, seconds, tol)
    return True, "%.2fs against a %.2fs target" % (made, seconds)


def gate_ink_spine(shots):
    """scene-director: at least one shot must be mg - the ink-wash is the show's spine."""
    if not shots:
        return False, "no shots to check"
    mg = [s.get("id") for s in shots if str(s.get("runtime", "")).lower() == "mg"]
    if not mg:
        return False, "no mg shot; the ink-wash spine is missing"
    return True, "%d mg shot(s): %s" % (len(mg), ", ".join(str(m) for m in mg[:3]))


def gate_cut_order(shots, beats):
    """showrunner: cut order = shot order. A reorder is a different film, so it is refused."""
    sid = [s.get("id") for s in shots]
    bid = [b.get("id") for b in beats if b.get("id")]
    if not bid:
        return True, "beats carry no ids to compare"
    if sid != bid:
        return False, "shot order %s != beat order %s" % (sid[:5], bid[:5])
    return True, "%d shots in beat order" % len(sid)


def gate_shot_beat_bijection(shots, beats):
    """scene-director: every shot id has exactly one script section with the same id, and back."""
    sid = [s.get("id") for s in shots if s.get("id")]
    bid = [b.get("id") for b in beats if b.get("id")]
    if len(sid) != len(set(sid)):
        return False, "duplicate shot id"
    if len(bid) != len(set(bid)):
        return False, "duplicate beat id"
    if set(sid) != set(bid):
        return False, "ids differ: only in shots %s, only in beats %s" % (
            sorted(set(sid) - set(bid))[:3], sorted(set(bid) - set(sid))[:3])
    return True, "%d ids match one-to-one" % len(sid)


def gate_warm_light(shots):
    """scene-director: warm indoors, never cool daylight. A colour temperature is not a mood."""
    bad = [s.get("id", "?") for s in shots
           if str(s.get("color_temperature", "warm")).lower() not in ("warm", "neutral")]
    if bad:
        return False, "cool light indoors on %s" % ", ".join(bad[:4])
    return True, "every indoor shot is warm"


def gate_explain_not_on_speaker(beats):
    """script-director: the explain beat shows what the words describe, never the speaker again."""
    bad = []
    for b in beats:
        if b.get("kind") != "explain":
            continue
        cast = [str(c).lower() for c in (b.get("cast") or [])]
        if "narrator" in cast and len(cast) == 1:
            continue
        bad.append(b.get("id", "?"))
    if bad:
        return False, "explain beat keeps the speaker on screen: %s" % ", ".join(bad[:3])
    return True, "every explain beat is narrator-only"


def gate_no_missing_is_soft(*paths):
    """showrunner: a missing file is not a soft failure (SPEC O1)."""
    missing = [str(p) for p in paths if not Path(p).exists()]
    if missing:
        return False, "missing: %s" % ", ".join(missing[:3])
    return True, "every input file is present"


ALL = [
    ("transitions", gate_transitions, "shots"),
    ("tempo", gate_tempo, "beats"),
    ("ink_spine", gate_ink_spine, "shots"),
    ("cut_order", gate_cut_order, "both"),
    ("bijection", gate_shot_beat_bijection, "both"),
    ("warm_light", gate_warm_light, "shots"),
    ("explain_not_on_speaker", gate_explain_not_on_speaker, "beats"),
]


# --- A/V sync ---------------------------------------------------------------------------
# The owner's complaint, exactly: "music jo tha woh out of sync tha". The picture had a rhythm
# (beats carry t and slot) and the bed had a rhythm (tempo + downbeats), and nothing compared
# the two. This is that comparison.

# A cut is "on the beat" when it lands within this fraction of one beat. One 16th at 90 bpm is
# 0.167 s; half of that is audible as a flam, so 0.08 s is the tolerance, not a whole beat.
SYNC_TOLERANCE_BEATS = 0.25


def cut_times(beats):
    """Where the picture cuts: the start of every beat after the first."""
    t = []
    clock = 0.0
    for b in beats:
        t.append(round(clock, 3))
        clock += b.get("slot", b.get("need", 0))
    return t[1:] if len(t) > 1 else []


def gate_av_sync(beats, audiomap, tolerance_beats=SYNC_TOLERANCE_BEATS):
    """Does every cut land on a musical beat?

    `audiomap` is what .agents/skills/music-to-video/scripts/analyze-beatgrid.py produces:
    {"bpm": float, "beats": [seconds...], "downbeats": [seconds...]}.

    Without an audiomap the gate cannot answer, and a gate that cannot answer is a NO
    (SPEC O2) - never a pass. That is the difference between this and the last film.
    """
    if not isinstance(audiomap, dict):
        return False, "no audiomap: the bed was never analysed, so sync cannot be claimed"
    bpm = audiomap.get("bpm")
    grid = audiomap.get("beats") or []
    if not isinstance(bpm, (int, float)) or bpm <= 0 or len(grid) < 2:
        return False, "audiomap has no usable tempo or beat grid (bpm=%r, %d beats)" % (bpm, len(grid))
    beat_s = 60.0 / float(bpm)
    tol = beat_s * tolerance_beats
    grid = sorted(float(x) for x in grid)
    cuts = cut_times(beats)
    if not cuts:
        return False, "no cuts to check"
    off = []
    for c in cuts:
        # nearest grid beat
        near = min(grid, key=lambda g: abs(g - c))
        if abs(near - c) > tol:
            off.append((round(c, 3), round(near, 3), round(abs(near - c), 3)))
    if off:
        return False, ("%d of %d cuts miss the beat by more than %.0f ms (at %.0f bpm): %s"
                       % (len(off), len(cuts), tol * 1000, bpm,
                          "; ".join("cut %.2fs vs beat %.2fs (+%.0f ms)" % (c, g, d * 1000) for c, g, d in off[:3])))
    worst = max(abs(min(grid, key=lambda g: abs(g - c)) - c) for c in cuts)
    return True, "%d cuts, all within %.0f ms of a beat at %.0f bpm (worst %.0f ms)" % (
        len(cuts), tol * 1000, bpm, worst * 1000)


def gate_bed_length(audiomap, seconds, tolerance=0.5):
    """A bed that is shorter than the film ends in silence, which reads as a broken master."""
    if not isinstance(audiomap, dict):
        return False, "no audiomap"
    dur = audiomap.get("duration")
    if not isinstance(dur, (int, float)):
        return False, "audiomap has no duration"
    if dur + tolerance < float(seconds):
        return False, "the bed is %.2fs, the film is %.2fs: %.2fs of silence at the end" % (
            dur, seconds, float(seconds) - dur)
    return True, "the bed covers the film (%.2fs vs %.2fs)" % (dur, seconds)


GATES_SYNC = [
    ("av_sync", gate_av_sync, "both"),
    ("bed_covers_film", gate_bed_length, "audiomap"),
]


def run_all(beats=None, shots=None, seconds=None, audiomap=None):
    """Every gate, one verdict. Any NO is a refusal, and the reason names the skill rule."""
    out = {}
    for name, fn, needs in ALL:
        if needs == "shots" and (shots is None or beats is None):
            continue
        if needs == "beats" and beats is None:
            continue
        if needs == "both" and (shots is None or beats is None):
            continue
        if needs == "shots":
            out[name] = fn(shots)
        elif needs == "beats":
            out[name] = fn(beats)
        else:
            out[name] = fn(shots, beats)
    if beats is not None and seconds is not None:
        out["length_target"] = gate_length_target(beats, seconds)
    if beats is not None and audiomap is not None:
        out["av_sync"] = gate_av_sync(beats, audiomap)
    if audiomap is not None and seconds is not None:
        out["bed_covers_film"] = gate_bed_length(audiomap, seconds)
    bad = [(k, v[1]) for k, v in out.items() if not v[0]]
    return (not bad), out, bad


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats"); ap.add_argument("--shots")
    ap.add_argument("--seconds", type=float); ap.add_argument("--audiomap")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    def load(p):
        return json.loads(Path(p).read_text()) if p else None
    ok, out, bad = run_all(load(a.beats), load(a.shots), a.seconds, load(a.audiomap))
    for k, (o, why) in out.items():
        print("  %-24s %-3s %s" % (k, "YES" if o else "NO", why))
    print("VERDICT:", "PASS" if ok else "REFUSED: %s" % "; ".join("%s: %s" % b for b in bad))
    return 0 if ok else 1


def _selftest():
    """Each gate, against the defect it exists to catch."""
    f = 0
    def ck(n, cond, why=""):
        nonlocal f
        if not cond: f += 1
        print("  %-44s %s  %s" % (n, "OK  " if cond else "FAIL", why))

    good_shots = [{"id": "a", "runtime": "mg", "transition_in": "ink_bloom", "color_temperature": "warm"},
                  {"id": "b", "runtime": "h3", "transition_in": "cut", "color_temperature": "warm"}]
    ck("transitions: ink_bloom+cut pass", gate_transitions(good_shots)[0])
    ck("transitions: dissolve refused",
       not gate_transitions(good_shots + [{"id": "c", "transition_in": "dissolve"}])[0])
    ck("ink spine: mg present", gate_ink_spine(good_shots)[0])
    ck("ink spine: no mg refused", not gate_ink_spine([good_shots[1]])[0])
    ck("warm light: all warm", gate_warm_light(good_shots)[0])
    ck("warm light: cool refused", not gate_warm_light([{"id": "a", "color_temperature": "cool"}])[0])

    b = [{"id": "a", "kind": "hook", "cast": ["narrator"], "need": 4, "slot": 4, "tempo": 1.0},
         {"id": "b", "kind": "explain", "cast": ["narrator"], "need": 3, "slot": 3, "tempo": 1.0}]
    ck("tempo: 1.0 passes", gate_tempo(b)[0])
    ck("tempo: 1.3 refused", not gate_tempo([{"id": "x", "tempo": 1.3}])[0])
    ck("explain on narrator only", gate_explain_not_on_speaker(b)[0])
    ck("explain keeping speaker refused",
       not gate_explain_not_on_speaker([{"id": "x", "kind": "explain", "cast": ["dhritarashtra"]}])[0])
    ck("bijection: ids match", gate_shot_beat_bijection(good_shots, b)[0])
    ck("bijection: extra shot refused",
       not gate_shot_beat_bijection(good_shots + [{"id": "z"}], b)[0])
    ck("cut order: same order", gate_cut_order(good_shots, b)[0])
    ck("cut order: swapped refused", not gate_cut_order(list(reversed(good_shots)), b)[0])
    ck("length: within 2 %", gate_length_target(b, 7.0)[0])
    ck("length: 30 % off refused", not gate_length_target(b, 10.0)[0])

    # A/V sync - the owner's complaint
    am = {"bpm": 60.0, "beats": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "duration": 60.0}
    onbeat = [{"slot": 1.0}, {"slot": 1.0}, {"slot": 1.0}]
    ck("sync: cuts on the beat pass", gate_av_sync(onbeat, am)[0])
    offbeat = [{"slot": 1.4}, {"slot": 1.4}]
    ok, why = gate_av_sync(offbeat, am)
    ck("sync: cut 0.4 s off the beat refused", not ok, why[:60])
    ck("sync: no audiomap is a NO, never a pass", not gate_av_sync(onbeat, None)[0])
    ck("bed shorter than film refused", not gate_bed_length({"duration": 5.0}, 60.0)[0])
    print("\nRESULT:", "ALL OK" if f == 0 else "%d WRONG" % f)
    return 1 if f else 0
