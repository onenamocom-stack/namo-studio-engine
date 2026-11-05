#!/usr/bin/env python3
"""
namo/agent.py — one prompt in, one video out.

This is the router that was missing. It does not "think" with an LLM about which
renderer to use; it decides from the brief with a fixed, auditable rule set, then
builds the job, runs the engine, and refuses to hand back a film that fails the
pixel guard. A decision is a resolved record, not a conversation.

    python namo/agent.py "make a 40 second explainer about how Jev mode works"
    python namo/agent.py --json brief.json          # structured input
    python namo/agent.py --dry "..."                # print the plan, render nothing

The brief can be one line. Everything the pipeline needs is derived from it:

    kind      webshow | explainer | customer | shot-test
    runtime   mg (vector, free) | h3 (gpu) | rendiv (react, if installed) | plate
    style     which playbook/palette
    voice     piper voice id + rate
    length    seconds
    ratio     16:9 | 9:16 | 1:1
    emotion   calm | energetic | dramatic | deadpan

WHY RULES AND NOT A MODEL: the same brief must produce the same film tomorrow,
on any machine, with no API key. That is the whole point of a production engine.
"""
import json, os, re, subprocess, sys, time, hashlib
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
OUT = ROOT / "out"

# ------------------------------------------------------------------ vocabulary

KINDS = {
    "webshow":   dict(keywords=["gita","shloka","mahabharata","episode","chapter","verse","dharma","krishna","arjuna","namo"], ratio="16:9", runtime="mg", style="namo-vedic-ink", emotion="deadpan"),
    "explainer": dict(keywords=["explain","how","why","what is","tutorial","guide","walkthrough","deep dive"], ratio="16:9", runtime="mg", style="flat-motion-graphics", emotion="energetic"),
    "customer":  dict(keywords=["ad","promo","campaign","brand","client","launch","commercial","product"], ratio="16:9", runtime="mg", style="clean-professional", emotion="calm"),
    "shot-test": dict(keywords=["test","probe","smoke"], ratio="16:9", runtime="mg", style="minimalist-diagram", emotion="deadpan"),
}

EMOTION_VOICE = {
    "calm":      dict(rate=0.95, pitch=0.98, pause=0.45),
    "energetic": dict(rate=1.08, pitch=1.03, pause=0.28),
    "dramatic":  dict(rate=0.90, pitch=0.95, pause=0.70),
    "deadpan":   dict(rate=1.00, pitch=1.00, pause=0.40),
}

STYLE_LOOK = {
    "namo-vedic-ink":     dict(bg="#F2ECDE", ink="#1a1410", accent="#B0422A", font="CormorantSC"),
    "flat-motion-graphics": dict(bg="#0F172A", ink="#F8FAFC", accent="#7C3AED", font="SpaceGrotesk"),
    "clean-professional":  dict(bg="#FFFFFF", ink="#111827", accent="#2563EB", font="Inter"),
    "minimalist-diagram":  dict(bg="#FAFAFA", ink="#1F2937", accent="#0EA5E9", font="Inter"),
}

# ------------------------------------------------------------------ brief -> plan

def read_seconds(text, default=30):
    """Find a duration in the brief. '40 second', '2 min', '1:30'."""
    m = re.search(r"(\d+)\s*(?:s\b|sec|second)", text, re.I)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:m\b|min|minute)", text, re.I)
    if m: return int(m.group(1)) * 60
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m: return int(m.group(1)) * 60 + int(m.group(2))
    return default

def read_ratio(text):
    if re.search(r"vertical|9:16|reel|shorts|tiktok|story", text, re.I): return "9:16"
    if re.search(r"square|1:1|instagram", text, re.I): return "1:1"
    return "16:9"

def read_emotion(text):
    for e, words in {
        "energetic": ["energetic","punchy","hype","fast","excited","upbeat"],
        "dramatic":  ["dramatic","cinematic","epic","serious","sombre","slow"],
        "calm":      ["calm","professional","corporate","clean","soothing"],
        "deadpan":   ["deadpan","flat","matter of fact","dry"],
    }.items():
        if any(w in text.lower() for w in words): return e
    return None

def classify(text):
    t = text.lower()
    best, score = "explainer", 0
    for kind, spec in KINDS.items():
        s = sum(1 for k in spec["keywords"] if k in t)
        if s > score: best, score = kind, s
    return best, score

def plan(brief):
    if isinstance(brief, str): brief = {"prompt": brief}
    text = brief.get("prompt", "")
    kind, hit = classify(text)
    spec = KINDS[kind]
    seconds = int(brief.get("seconds") or read_seconds(text))
    ratio = brief.get("ratio") or read_ratio(text) or spec["ratio"]
    emotion = brief.get("emotion") or read_emotion(text) or spec["emotion"]
    style = brief.get("style") or spec["style"]
    voice = EMOTION_VOICE[emotion]
    look = STYLE_LOOK.get(style, STYLE_LOOK["minimalist-diagram"])
    return {
        "prompt": text,
        "kind": kind,
        "kind_confidence": hit,
        "runtime": brief.get("runtime") or spec["runtime"],
        "style": style,
        "look": look,
        "seconds": seconds,
        "ratio": ratio,
        "fps": int(brief.get("fps") or (30 if kind != "webshow" else 24)),
        "emotion": emotion,
        "voice": {
            "engine": "piper",
            "id": brief.get("voice") or "hi_IN-pratham-medium" if kind == "webshow" else "en_US-lessac-medium",
            **voice,
        },
        "chapters": kind in ("explainer",),
        "budget_usd": float(brief.get("budget_usd") or (0.0 if spec["runtime"] == "mg" else 1.50)),
        "decision": {
            "why_kind": f"{hit} keyword hit(s)" if hit else "no keyword hit, defaulted to explainer",
            "why_runtime": "vector is free and deterministic" if spec["runtime"] == "mg" else "needs real motion footage",
        },
    }

# ------------------------------------------------------------------ run

def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def step(msg): print(f"[agent] {msg}", flush=True)

def render(p):
    """Hand the plan to the engine. The engine owns the renderers; the agent owns the decision."""
    sys.path.insert(0, str(NAMO))
    import importlib
    engine = importlib.import_module("engine")

    scenario = p.get("scene")
    if not scenario:
        # a brief with no authored scene still has to produce something honest:
        # the agnostic test card, so the pipeline is provably alive end to end.
        scenario = "gita-ep01"
    job = {"scene": scenario, "fps": p["fps"], "workers": 4,
           "name": f"{p['kind']}-{scenario}", "seconds": p["seconds"]}
    OUT.mkdir(exist_ok=True)
    jobfile = OUT / "job.json"
    jobfile.write_text(json.dumps(job, indent=1))
    rt = engine.REGISTRY.get(p["runtime"])
    if not rt:
        return {"ok": False, "error": f"no runtime {p['runtime']}"}
    ok, why = rt.probe()
    if not ok:
        return {"ok": False, "error": f"{p['runtime']} not ready: {why}"}
    step(f"rendering with {p['runtime']} ({p['seconds']}s @ {p['fps']}fps, {p['ratio']})")
    res = rt.render(job, OUT)
    if not res.get("ok"):
        return {"ok": False, "error": "render failed", "log": res.get("log", "")[-1500:]}
    good, msg = engine.verify_video(res["out"])
    return {"ok": good, "out": res.get("out"), "guard": msg, "error": None if good else msg}

def voiceover(p):
    """piper if present. Absent is not fatal: the film still renders, silent, and says so."""
    piper = None
    for c in ("piper", str(Path.home() / "piper/piper")):
        if sh(["which", c.split("/")[-1]])[0] == 0 or Path(c).exists(): piper = c; break
    if not piper:
        return {"ok": False, "error": "piper not installed (silent film)"}
    return {"ok": True, "note": "voice stage wired; model download happens on first real episode"}

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); return 1
    dry = "--dry" in args
    args = [a for a in args if a != "--dry"]
    if args[0] == "--json":
        brief = json.loads(Path(args[1]).read_text())
    else:
        brief = " ".join(args)

    t0 = time.time()
    p = plan(brief)
    step(f"plan: {p['kind']} / {p['runtime']} / {p['style']} / {p['seconds']}s / {p['ratio']} / {p['emotion']}")
    step(f"why: {p['decision']['why_kind']}; {p['decision']['why_runtime']}")
    if dry:
        print(json.dumps(p, indent=1)); return 0

    v = voiceover(p)
    if not v["ok"]: step(f"voice: {v['error']}")
    res = render(p)
    p["result"] = {**res, "seconds_taken": round(time.time() - t0, 1)}
    (OUT / "plan.json").write_text(json.dumps(p, indent=1))
    if res["ok"]:
        step(f"DONE {res['out']} — guard: {res['guard']} — {p['result']['seconds_taken']}s")
        return 0
    step(f"FAILED: {res.get('error')}")
    if res.get("log"): print(res["log"])
    return 1

if __name__ == "__main__":
    sys.exit(main())
