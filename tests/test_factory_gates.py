#!/usr/bin/env python3
"""End-to-end: does factory.run_job actually gate the script before it renders?

This is the test that was missing. Every module passed on its own while factory.py called none
of them, so "wired" was true of the laptop and false of the repo. This imports factory and
asserts on the record it produces - the same record status.json gets.
"""
import json, os, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "namo"))
import factory

fails = 0


def ck(name, cond, why=""):
    global fails
    if not cond:
        fails += 1
    print("  %-52s %s  %s" % (name, "OK  " if cond else "FAIL", why[:90]))


# 1. a job with no audiomap must be BLOCKED, and the reason must name the sync gate
rec = factory.run_job({"id": "gate-probe", "prompt": "gita chapter 1 shloka 1, 60 seconds"})
ck("factory gates before rendering", rec["state"] == "BLOCKED", rec["state"])
ck("the record carries every gate verdict", isinstance(rec.get("gates"), dict) and rec["gates"],
   "%d gates" % len(rec.get("gates") or {}))
ck("av_sync is among them and says NO", rec.get("gates", {}).get("av_sync", [True])[0] is False,
   str(rec.get("gates", {}).get("av_sync")))
ck("the script was written, not skipped", (rec.get("script") or {}).get("beats", 0) > 0,
   str(rec.get("script")))
ck("the reason names the sync gate", "av_sync" in (rec.get("reason") or ""), (rec.get("reason") or "")[:80])
ck("nothing was rendered", not rec.get("out"), str(rec.get("out")))

# 2. a job WITH an audiomap must get past the gate (it may still fail later for other reasons,
#    so the assertion is that it is no longer BLOCKED for the sync reason)
am = {"bpm": 60.0, "beats": [float(i) for i in range(200)], "duration": 200.0}
rec2 = factory.run_job({"id": "gate-probe-2", "prompt": "gita chapter 1 shloka 1, 60 seconds",
                        "audiomap": am})
ck("with a bed analysed, the sync gate passes", rec2.get("gates", {}).get("av_sync", [False])[0],
   str(rec2.get("gates", {}).get("av_sync")))
# The engine is not bootstrapped in CI, so "mg" is legitimately not proven here. What this test
# asserts is that the SCRIPT gate no longer blocks - the renderer check is a separate, later gate.
ck("and the script gate no longer blocks", "script gate" not in (rec2.get("reason") or ""),
   rec2.get("reason") or rec2["state"])

print("\nRESULT:", "ALL OK" if fails == 0 else "%d WRONG" % fails)
sys.exit(1 if fails else 0)
