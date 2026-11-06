#!/usr/bin/env python3
"""
namo/gatekeeper.py - one question for the whole script: may this be rendered?

Measured gap this closes: writer.py produces a beat sheet and gates.py answers YES/NO about it,
but factory.py called neither. Both existed and neither ran, which is the same as not existing.

This module is the wire between them and the factory:

    plan + brief  -> writer.fitting_length()   the film the script can honestly carry
                  -> writer.to_shots()         a slot per beat, never padded
                  -> gates.run_all()            the skills' rules, + A/V sync when a bed was analysed
                  -> VERDICT                    any NO blocks the render, with the reason named

    python namo/gatekeeper.py --brief "gita 1.1, 60 seconds"
    python namo/gatekeeper.py --brief "..." --audiomap audiomap.json --json

A gate that cannot run is a NO. A missing audiomap therefore blocks the sync claim rather than
allowing it: the last shipped film passed every check and had its music out of sync.
"""
import argparse, json, sys
from pathlib import Path

NAMO = Path(__file__).resolve().parent
if str(NAMO) not in sys.path:
    sys.path.insert(0, str(NAMO))

import writer
import gates


def _shots_from(beats, runtime):
    """One shot per beat, with ids, in beat order, ink-wash as the spine (scene-director)."""
    out = []
    for i, b in enumerate(beats):
        out.append({
            "id": b.setdefault("id", "b%02d" % i),
            "runtime": runtime,
            "transition_in": "ink_bloom" if i == 0 else "cut",
            "color_temperature": "warm",
            "picture": b.get("picture"),
        })
    return out


def gate(plan, brief="", audiomap=None, scene_shots=None):
    """Returns {ok, seconds, beats, shots, results, bad}. Never raises for a film reason:
    a refusal is a result, and the caller turns it into BLOCKED."""
    want = float(plan.get("seconds") or 60)
    runtime = str(plan.get("runtime") or "mg").lower()

    beats, seconds = writer.fitting_length(brief or plan.get("brief", ""), want)

    # the writer's own gates come first: they are about the script, not the show
    shots, rep = writer.to_shots(beats, seconds)
    wq = writer.gate_beats(shots, seconds)
    wok, wbad = writer.report(wq)

    # the picture obeys the bed: snap cuts to the analysed beats before any gate judges them
    align = {"ok": False, "why": "no audiomap"}
    if audiomap is not None:
        shots, align = gates.align_to_beats(shots, audiomap)

    show_shots = scene_shots if scene_shots is not None else _shots_from(shots, runtime)
    gok, results, gbad = gates.run_all(beats=shots, shots=show_shots, seconds=seconds,
                                       audiomap=audiomap)

    bad = [("writer." + k, "refused") for k in wbad] + list(gbad)
    for k, v in wq.items():
        results["writer." + k] = (v, "written" if v else "refused")
    results["align"] = (bool(align.get("ok")), "snapped %s/%s cuts, max shift %ss" % (
        align.get("snapped"), align.get("cuts"), align.get("max_shift"))
        if align.get("ok") else str(align.get("why")))
    if not align.get("ok"):
        bad = bad + [("align", str(align.get("why")))]
    return {"ok": (not bad), "seconds": seconds, "beats": shots, "shots": show_shots,
            "results": results, "bad": bad, "align": align}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--runtime", default="mg")
    ap.add_argument("--audiomap")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    plan = {"seconds": a.seconds, "runtime": a.runtime}
    am = json.loads(Path(a.audiomap).read_text()) if a.audiomap else None
    r = gate(plan, brief=a.brief, audiomap=am)

    if a.json:
        print(json.dumps({"ok": r["ok"], "seconds": r["seconds"], "beats": r["beats"],
                          "gates": {k: [v[0], v[1]] for k, v in r["results"].items()},
                          "bad": r["bad"]}, ensure_ascii=False, indent=1))
    else:
        print("film: %.0fs, %d beats" % (r["seconds"], len(r["beats"])))
        for k, (o, why) in r["results"].items():
            print("  %-32s %-3s %s" % (k, "YES" if o else "NO", why[:88]))
        print("VERDICT:", "RENDER" if r["ok"] else "REFUSED: " + "; ".join("%s: %s" % b for b in r["bad"])[:400])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
