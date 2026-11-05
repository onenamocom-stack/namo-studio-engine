#!/usr/bin/env python3
"""
namo/factory.py — the factory runs itself.

No human in the loop for routine work. The factory:
  1. reads the queue          (queue.json)
  2. plans each job           (agent.plan — deterministic, no model)
  3. checks feasibility       (does the scene exist? is the runtime ready?)
  4. renders what it can      (engine registry only)
  5. verifies pixels          (a blank film is a failure, not an output)
  6. records what happened    (status.json)
  7. refuses loudly           (infeasible => BLOCKED, with the exact reason)

A failure is recorded with its cause instead of being found by a human three days later.

    python namo/factory.py --once
    python namo/factory.py --once --dry
    python namo/factory.py --status
"""
import json, sys, time, traceback
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
QUEUE, STATUS, OUT = ROOT / "queue.json", ROOT / "status.json", ROOT / "out"

sys.path.insert(0, str(NAMO))
import agent as router
import engine

def load(p, d):
    try: return json.loads(Path(p).read_text())
    except Exception: return d

def save(p, o): Path(p).write_text(json.dumps(o, indent=1))

def feasible(plan):
    scene = plan.get("scene") or router.SCENE_FOR_KIND.get(plan["kind"])
    if not scene:
        have = ", ".join(sorted(router.SCENES_AVAILABLE())) or "none"
        return False, f"no scene for kind '{plan['kind']}' (have: {have})"
    if scene not in router.SCENES_AVAILABLE():
        return False, f"scene '{scene}' is not on disk"
    rt = engine.REGISTRY.get(plan["runtime"])
    if not rt: return False, f"unknown runtime '{plan['runtime']}'"
    ok, why = rt.probe()
    return (True, "ok") if ok else (False, f"{plan['runtime']} not ready: {why}")

def run_job(job):
    t0 = time.time()
    rec = {"id": job.get("id") or f"job-{int(t0)}", "brief": job.get("prompt",""),
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))}
    plan = router.plan(job)
    rec["plan"] = {k: plan.get(k) for k in ("kind","runtime","style","seconds","ratio","fps","emotion")}
    ok, why = feasible(plan)
    if not ok:
        rec.update(state="BLOCKED", reason=why, seconds=round(time.time()-t0,1)); return rec
    plan["scene"] = plan.get("scene") or router.SCENE_FOR_KIND[plan["kind"]]
    res = router.render(plan)
    if res.get("ok"): rec.update(state="DONE", out=res["out"], guard=res["guard"])
    else: rec.update(state="FAILED", reason=res.get("error"), log=(res.get("log") or "")[-800:])
    rec["seconds"] = round(time.time()-t0, 1)
    return rec

def once(dry=False):
    jobs = load(QUEUE, {"jobs": []}).get("jobs", [])
    st = load(STATUS, {"runs": []})
    done = {r["id"] for r in st["runs"] if r["state"] == "DONE"}
    todo = [j for j in jobs if (j.get("id") or j.get("prompt")) not in done]
    if not todo:
        print("factory: queue empty or fully done"); return 0
    print(f"factory: {len(todo)} job(s)")
    for job in todo:
        jid = job.get("id") or job.get("prompt","")[:40]
        try:
            rec = {"id": jid, "state": "DRY", "plan": router.plan(job)} if dry else run_job(job)
        except Exception as e:
            rec = {"id": jid, "state": "CRASHED", "reason": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc()[-800:]}
        st["runs"].append(rec); save(STATUS, st)
        print(f"  {rec['id']:28s} {rec['state']:8s} {rec.get('reason','') or rec.get('guard','')}")
    counts = {}
    for r in st["runs"]: counts[r["state"]] = counts.get(r["state"],0)+1
    print("factory:", counts)
    last = st["runs"][-len(todo):]
    return 0 if not any(r["state"] in ("FAILED","CRASHED") for r in last) else 1

def status():
    st = load(STATUS, {"runs": []})
    if not st["runs"]: print("no runs yet"); return 0
    for r in st["runs"][-20:]:
        print(f"{r['id']:28s} {r['state']:8s} {r.get('reason','') or r.get('out','')}")
    return 0

if __name__ == "__main__":
    if "--status" in sys.argv: sys.exit(status())
    sys.exit(once(dry="--dry" in sys.argv))
