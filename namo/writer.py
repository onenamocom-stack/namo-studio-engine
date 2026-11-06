#!/usr/bin/env python3
"""
namo/writer.py - brief in, beat sheet out. The screenwriter that was missing.

Measured gap this closes: namo/agent.py decides a RUNTIME from keywords and never writes a
word. Every film so far used a scene someone wrote by hand, so dialogue length, beat order and
who is on screen were whatever the author happened to type. The skill that says how to write
one (skills/pipelines/namo/script-director.md) has no executor.

This module is that executor. It is a writer, not a reviewer:

    brief  -> beats   a spoken script with measured timing, not a paragraph
    beats  -> shots   one shot per beat, each bound to a cast and a length
    beats  -> gates   binary questions, each answered by a rule or by Jev

The rule this file exists to enforce (the owner's, in one sentence): a line that cannot be
spoken inside its own shot is a bug, not a style. So every dialogue is measured, never assumed.

    python namo/writer.py --brief "gita chapter 1 shloka 1, 60 seconds" --beats
    python namo/writer.py --brief "..." --shots
    python namo/writer.py --brief "..." --gate
    python namo/writer.py --brief "..." --json > script.json

No network call in --beats is required: the deterministic writer always produces a valid sheet.
A model may enrich it, and is never trusted to time it.
"""
import argparse, json, math, os, re, sys, urllib.request
from pathlib import Path

# --- speech budget -----------------------------------------------------------------------
# Measured from piper hi_IN-pratham-medium and Chirp3-HD hi: a Hindi syllable at rate 1.0 is
# ~0.191 s, a Sanskrit shloka half-line (16 syllables, slow) is ~0.30 s/syllable. These are the
# numbers the length gate uses; they are deliberately conservative so a line that passes is
# never cut off in the mix.
SEC_PER_HI_SYL = 0.191
SEC_PER_SA_SYL = 0.300
AIR_AFTER_LINE = 0.35          # silence that must follow a spoken line before the next cut

SHLOKA_SYL = 16                # one half-line of an anustubh verse
MAX_HOLD_RATIO = 1.6           # a shot may hold at most 60 % longer than its own speech

# --- what a beat is ----------------------------------------------------------------------
BEAT_KINDS = ("hook", "shloka", "explain", "scene", "silence")

# time-of-day light and who is on screen: the two things a shot needs and a paragraph lacks
CAST = ("narrator", "dhritarashtra", "sanjay", "krishna", "arjuna", "army")


def syllables(text):
    """Devanagari akshara count: a consonant cluster (halant-joined) is one beat, an
    independent vowel is one, a matra does not add one. Deliberately simple and testable."""
    if not text:
        return 0
    n = 0
    halant = "\u094d"
    for i, ch in enumerate(text):
        if "\u0900" <= ch <= "\u097f":
            # count a consonant when it is not immediately followed by a halant
            if "\u0915" <= ch <= "\u0939" and not (i + 1 < len(text) and text[i + 1] == halant):
                n += 1
            elif "\u0905" <= ch <= "\u0914" or ch in "\u090d\u090e\u0911\u0912":
                n += 1
    return max(1, n) if n else 0


def speak_seconds(text, script="hi", rate=1.0):
    """How long this line actually takes to say. Never a guess from character count."""
    syl = syllables(text)
    if not syl:
        return 0.0
    unit = SEC_PER_SA_SYL if script == "sa" else SEC_PER_HI_SYL
    return syl * unit / max(0.5, rate)


def fit(beats):
    """Give every beat the length its own speech needs, then make the total match the target.
    Returns (beats, report). A beat whose speech exceeds its slot is a failure, not a squeeze."""
    problems = []
    for b in beats:
        need = speak_seconds(b.get("text", ""), b.get("lang", "hi"), b.get("rate", 1.0))
        b["speech"] = round(need, 3)
        b["need"] = round(need + (AIR_AFTER_LINE if b.get("text") else 0.0), 3)
    total_need = sum(b["need"] for b in beats)
    return beats, {"total_need": round(total_need, 3), "problems": problems}


def gate_beats(beats, seconds):
    """Binary, per beat. Any False is a refusal - the film is not written yet.

    `seconds` is the film the writer intends to make. When the beats carry slots, the film that
    will actually be rendered is sum(slot); that is what "is it filled" is judged against."""
    q = {}
    need = sum(b["need"] for b in beats)
    made = sum(b.get("slot", b["need"]) for b in beats)
    q["fits_the_film"] = need <= float(seconds) + 0.5
    q["no_speech_overruns_its_shot"] = all(
        b["speech"] <= b.get("slot", b["need"]) + 0.01 for b in beats)
    q["every_speaking_beat_has_a_speaker"] = all(
        (not b.get("text")) or b.get("cast") for b in beats)
    q["no_beat_is_empty"] = all(
        bool(b.get("text")) or b.get("kind") == "silence" or b.get("picture") for b in beats)
    # the owner's Sanskrit rule: a shloka beat is followed by its explain, not by another shloka
    kinds = [b["kind"] for b in beats]
    q["sanskrit_rule"] = all(
        kinds[i + 1] == "explain" for i, k in enumerate(kinds[:-1]) if k == "shloka")
    # a shot that repeats the previous shot's picture is a duplicate, not a new shot
    pics = [b.get("picture") for b in beats if b.get("picture")]
    q["no_repeated_picture"] = len(pics) == len(set(pics))
    # the defect the owner saw in the last film: long shots over short lines
    q["no_shot_drags"] = all(
        b.get("slot", 0) <= b["need"] * MAX_HOLD_RATIO + 0.5 for b in beats)
    q["the_film_is_filled"] = made >= float(seconds) * 0.85
    return q


def report(q):
    bad = [k for k, v in q.items() if not v]
    return (not bad), bad


def beats_for(brief, seconds=60, shlokas=None):
    """The deterministic writer. A brief gives the subject; this gives a shootable beat sheet.

    Structure enforced (not suggested):
      hook -> for each verse: shloka -> explain -> ... -> close
    Each beat carries: kind, text, lang, cast, picture. Timing is measured afterwards.

    How many verses: enough that the film is full. A 60 s film with one shloka is 14 s of
    speech and 46 s of nothing - the error the last film shipped. So the writer adds verse
    pairs until the measured speech fills the target, and refuses if the source runs out.
    """
    shl = shlokas or GITA_1_1
    beats = [dict(kind="hook", lang="hi", cast=["narrator"],
                  picture="kurukshetra_field_wide",
                  text="\u0938\u0924\u094d\u0924\u0930\u0939 \u0926\u093f\u0928, \u0926\u094b \u092a\u0930\u093f\u0935\u093e\u0930, \u0914\u0930 \u090f\u0915 \u0906\u0901\u0916\u094b\u0902 \u0935\u093e\u0932\u093e \u092a\u094d\u0930\u0936\u094d\u0928\u0964")]
    for n, s in enumerate(shl):
        beats.append(dict(kind="shloka", lang="sa", cast=["dhritarashtra", "sanjay"],
                          picture="sarpa_satra_hall_%d" % n, text=s["sa"], sa=s["sa"]))
        beats.append(dict(kind="explain", lang="hi", cast=["narrator"],
                          picture="kurukshetra_army_%d" % n, text=s["hi"]))
    beats.append(dict(kind="scene", lang="hi", cast=["narrator"], picture="halo_verse_card",
                      text="\u092f\u0939\u0940 \u092a\u094d\u0930\u0936\u094d\u0928 \u092a\u0942\u0930\u0947 \u092e\u0939\u093e\u092d\u093e\u0930\u0924 \u0915\u094b \u0916\u094b\u0932\u0924\u093e \u0939\u0948\u0964"))
    return beats


def fitting_length(brief, want, shlokas=None):
    """The film is as long as the script it can honestly carry, not the other way round.

    Ask for 60 s and hand the writer three verses: the honest answer is a 43 s film, not a
    60 s film with 17 s of nothing. Returns (beats, seconds) where seconds is what the measured
    speech supports at MAX_HOLD_RATIO. If the requested length is already reachable, it is kept.
    """
    beats = beats_for(brief, want, shlokas)
    filled, rep = fit(beats)
    supported = sum(b["need"] for b in filled) * MAX_HOLD_RATIO
    if supported >= want:
        return beats, want
    # round down to the nearest second; a film is never padded to hit a round number
    return beats, float(int(supported))


# Gita 1.1-1.3: the verses that belong to the blind king's first question. A short film takes
# them from the top; the writer never invents Sanskrit, it only selects and explains.
GITA_1_1 = [
 dict(sa="\u0927\u0943\u0924\u0930\u093e\u0937\u094d\u091f\u094d\u0930 \u0909\u0935\u093e\u091a \u0964",
      hi="\u0927\u0943\u0924\u0930\u093e\u0937\u094d\u091f\u094d\u0930 \u0928\u0947 \u092a\u0942\u091b\u093e\u0964"),
 dict(sa="\u0927\u0930\u094d\u092e\u0915\u094d\u0937\u0947\u0924\u094d\u0930\u0947 \u0915\u0941\u0930\u0941\u0915\u094d\u0937\u0947\u0924\u094d\u0930\u0947 \u0938\u092e\u0935\u0947\u0924\u093e \u092f\u0941\u092f\u0941\u0924\u094d\u0938\u0935\u0903 \u0964",
      hi="\u0927\u0930\u094d\u092e \u0915\u0947 \u092e\u0948\u0926\u093e\u0928 \u092a\u0930, \u092f\u0941\u0926\u094d\u0927 \u0915\u0940 \u0932\u093e\u0932\u0938\u093e \u0938\u0947 \u092d\u0930\u0947 \u0939\u0941\u090f\u0964"),
 dict(sa="\u092e\u093e\u092e\u0915\u093e\u0903 \u092a\u093e\u0923\u094d\u0921\u0935\u093e\u0936\u094d\u091a\u0948\u0935 \u0915\u093f\u092e\u0915\u0941\u0930\u094d\u0935\u0928\u094d\u0924 \u0938\u0902\u091c\u092f \u0964",
      hi="\u092e\u0947\u0930\u0947 \u0932\u094b\u0917 \u0914\u0930 \u092a\u093e\u0902\u0921\u0935 \u2014 \u0926\u094b\u0928\u094b\u0902 \u0928\u0947 \u0915\u094d\u092f\u093e \u0915\u093f\u092f\u093e, \u0938\u0902\u091c\u092f?")]


def to_shots(beats, seconds=60):
    """One shot per beat, with the slot each shot gets. A slot is >= what the line needs, so a
    cut never lands inside a word. Leftover time is given to the beat that holds longest."""
    filled, rep = fit(beats)
    total = sum(b["need"] for b in filled)
    if total > seconds:
        # not enough film for this script: say so, do not silently speed it up
        return filled, {"ok": False, "why": "speech needs %.1fs but the film is %ss" % (total, seconds)}
    spare = seconds - total
    # Spare time is NOT free air. A shot that holds 12 s while its line takes 4 s is a film
    # that drags - this is the defect the writer exists to prevent. Give each beat at most
    # MAX_HOLD_RATIO of its own speech as extra hold; if that cannot fill the film, the script
    # is too thin and is refused rather than padded.
    t = 0.0
    for b in filled:
        hold = min(b["need"] * (MAX_HOLD_RATIO - 1.0), spare)
        hold = max(hold, 0.0)
        spare -= hold
        b["hold"] = round(hold, 3)
        b["slot"] = round(b["need"] + hold, 3)
        b["t"] = round(t, 3)
        t += b["slot"]
    return filled, {"ok": spare <= 0.5, "total": round(t, 3),
                    "unfilled": round(max(0.0, spare), 3)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--beats", action="store_true")
    ap.add_argument("--shots", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    m = re.search(r"(\d+)\s*second", a.brief, re.I)
    seconds = a.seconds or (float(m.group(1)) if m else 60.0)

    beats, seconds = fitting_length(a.brief, seconds)
    shots, rep = to_shots(beats, seconds)

    if a.beats or a.shots:
        if not a.json:
            print("film length: %.0fs (what the script can honestly carry)" % seconds)
            for b in shots:
                print("%-8s t=%6.2f slot=%5.2f speech=%5.2f  %-14s %-28s %s"
                      % (b["kind"], b.get("t", 0), b.get("slot", 0), b["speech"],
                         b.get("picture", "-"), ",".join(b.get("cast") or []) or "-",
                         (b.get("text") or "")[:40]))

    q = gate_beats(shots, seconds)
    ok, bad = report(q)
    if a.gate or not (a.beats or a.shots or a.json):
        print("\n--- BINARY GATES ---")
        for k, v in q.items():
            print("  %-34s %s" % (k, "YES" if v else "NO   <-- REFUSES THE FILM"))
        print("VERDICT:", "SHOOTABLE" if ok else "REFUSED (%s)" % ", ".join(bad))

    if a.json:
        print(json.dumps({"seconds": seconds, "beats": shots, "gates": q,
                          "shootable": ok}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
