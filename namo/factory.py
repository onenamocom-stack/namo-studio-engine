#!/usr/bin/env python3
"""
namo/factory.py — the factory runs itself.

No human in the loop for routine work. The factory:
  1. reads the queue          (queue.json)
  2. plans each job           (agent.plan — deterministic, no model)
  3. writes the script        (namo/writer.py - every line MEASURED, never assumed)
  3b. gates that script       (namo/gatekeeper.py - the skills' rules as YES/NO, incl. A/V sync)
  3c. checks feasibility      (does the scene exist? is the runtime ready?)
  4. renders what it can      (engine registry only)
  5. verifies pixels          (a blank film is a failure, not an output)
  6. records what happened    (status.json)
  7. refuses loudly           (infeasible => BLOCKED, with the exact reason; exit 1 if any job BLOCKED/FAILED/CRASHED)

A failure is recorded with its cause instead of being found by a human three days later.

    python namo/factory.py --once
    python namo/factory.py --once --dry
    python namo/factory.py --status
"""
import hashlib, json, sys, time, traceback
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
QUEUE, STATUS, OUT = ROOT / "queue.json", ROOT / "status.json", ROOT / "out"

sys.path.insert(0, str(NAMO))
import agent as router
import engine
import gatekeeper

def load(p, d):
    try: return json.loads(Path(p).read_text())
    except Exception: return d

def save(p, o): Path(p).write_text(json.dumps(o, indent=1))

def job_id(job):
    """One stable id for recording and lookup: the job's own id, else a hash of the normalised brief."""
    if job.get("id"): return job["id"]
    brief = {k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in job.items()}
    return "job-" + hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()[:12]

def feasible(plan):
    scene = plan.get("scene") or router.SCENE_FOR_KIND.get(plan["kind"])
    if not scene:
        have = ", ".join(sorted(router.SCENES_AVAILABLE())) or "none"
        return False, f"no scene for kind '{plan['kind']}' (have: {have})"
    if scene not in router.SCENES_AVAILABLE():
        return False, f"scene '{scene}' is not on disk"
    rt = engine.REGISTRY.get(plan["runtime"])
    if not rt: return False, f"unknown runtime '{plan['runtime']}'"
    if getattr(rt, "styles", None) and plan["style"] not in rt.styles:
        return False, f"{plan['runtime']} renders style {', '.join(rt.styles)} only, not '{plan['style']}'"
    ok, why = rt.probe()
    return (True, "ok") if ok else (False, f"{plan['runtime']} not ready: {why}")

def run_job(job):
    t0 = time.time()
    rec = {"id": job_id(job), "brief": job.get("prompt",""),
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))}
    plan = router.plan(job)
    rec["plan"] = {k: plan.get(k) for k in ("kind","runtime","style","seconds","ratio","fps","emotion")}
    plan["scene"] = plan.get("scene") or router.SCENE_FOR_KIND.get(plan["kind"])

    # ORDER MATTERS. The script is judged first, because "is the script worth shooting" does not
    # depend on whether a renderer happens to be ready - and asking the renderer first hid every
    # script verdict behind an unrelated "unknown runtime". A test caught that; keep it fixed.
    try:
        keep = gatekeeper.gate(plan, brief=job.get("prompt", ""), audiomap=job.get("audiomap"))
    except Exception as e:
        rec.update(state="CRASHED", reason="gatekeeper: %s: %s" % (type(e).__name__, str(e)[:300]),
                   trace=traceback.format_exc()[-1400:], seconds=round(time.time()-t0, 1))
        return rec
    rec["script"] = {"seconds": keep["seconds"], "beats": len(keep["beats"])}
    rec["gates"] = {k: [bool(v[0]), v[1][:200]] for k, v in keep["results"].items()}
    if not keep["ok"]:
        rec.update(state="BLOCKED",
                   reason="script gate: " + "; ".join("%s: %s" % (k, w) for k, w in keep["bad"])[:700],
                   seconds=round(time.time()-t0, 1))
        return rec
    plan["seconds"] = keep["seconds"]

    # The script is honest; now ask whether anything can actually render it.
    ok, why = feasible(plan)
    if not ok:
        rec.update(state="BLOCKED", reason=why, seconds=round(time.time()-t0, 1))
        return rec

    try:
        res = router.render(plan)
    except Exception as e:
        rec.update(state="CRASHED", reason="%s: %s" % (type(e).__name__, str(e)[:400]),
                   trace=traceback.format_exc()[-1400:], seconds=round(time.time()-t0, 1))
        return rec
    if res.get("ok"): rec.update(state="DONE", out=res["out"], guard=res["guard"], audio=res.get("audio"))
    else: rec.update(state="FAILED", reason=res.get("error"), cmd=res.get("cmd"), cwd=res.get("cwd"),
                   log=(res.get("log") or "")[-1500:])
    rec["seconds"] = round(time.time()-t0, 1)
    return rec

def dry_run(job, jid):
    """Plan + script gate + feasibility, no render. Same order as run_job, so --dry tells the truth."""
    plan = router.plan(job)
    plan["scene"] = plan.get("scene") or router.SCENE_FOR_KIND.get(plan["kind"])
    try:
        keep = gatekeeper.gate(plan, brief=job.get("prompt", ""), audiomap=job.get("audiomap"))
    except Exception as e:
        return {"id": jid, "state": "BLOCKED", "reason": "gatekeeper: %s" % e, "plan": plan}
    if not keep["ok"]:
        return {"id": jid, "state": "BLOCKED", "plan": plan,
                "reason": "script gate: " + "; ".join("%s: %s" % (k, w) for k, w in keep["bad"])[:400],
                "gates": {k: [bool(v[0]), v[1][:200]] for k, v in keep["results"].items()},
                "script": {"seconds": keep["seconds"], "beats": len(keep["beats"])}}
    plan["seconds"] = keep["seconds"]
    ok, why = feasible(plan)
    return {"id": jid, "state": "DRY" if ok else "BLOCKED", "reason": "feasible" if ok else why,
            "plan": plan, "gates": {k: [bool(v[0]), v[1][:200]] for k, v in keep["results"].items()},
            "script": {"seconds": keep["seconds"], "beats": len(keep["beats"])}}

def once(dry=False):
    jobs = load(QUEUE, {"jobs": []}).get("jobs", [])
    st = load(STATUS, {"runs": []})
    done = {r["id"] for r in st["runs"] if r["state"] == "DONE"}
    todo = [j for j in jobs if job_id(j) not in done]
    if not todo:
        print("factory: queue empty or fully done"); return 0
    print(f"factory: {len(todo)} job(s)")
    for job in todo:
        jid = job_id(job)
        try:
            rec = dry_run(job, jid) if dry else run_job(job)
        except Exception as e:
            rec = {"id": jid, "state": "CRASHED", "reason": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc()[-800:]}
        st["runs"].append(rec); save(STATUS, st)
        print(f"  {rec['id']:28s} {rec['state']:8s} {rec.get('reason','') or rec.get('guard','')}")
    counts = {}
    for r in st["runs"]: counts[r["state"]] = counts.get(r["state"],0)+1
    print("factory:", counts)
    last = st["runs"][-len(todo):]
    return 0 if not any(r["state"] in ("BLOCKED","FAILED","CRASHED") for r in last) else 1

def status():
    st = load(STATUS, {"runs": []})
    if not st["runs"]: print("no runs yet"); return 0
    for r in st["runs"][-20:]:
        print(f"{r['id']:28s} {r['state']:8s} {r.get('reason','') or r.get('out','')}")
    return 0

if __name__ == "__main__":
    if "--status" in sys.argv: sys.exit(status())
    sys.exit(once(dry="--dry" in sys.argv))
