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
    runtime   mg (lemo ink-wash) | rd (rendiv explainers); GPU/H3 episodes are namo-studio's job
    style     which playbook/palette
    voice     voice id (piper or Chirp3-HD; the id names its engine) + rate
    length    seconds
    ratio     16:9 | 9:16 | 1:1
    emotion   calm | energetic | dramatic | deadpan

WHY RULES AND NOT A MODEL: the same brief must produce the same film tomorrow,
on any machine, with no API key. That is the whole point of a production engine.
"""
import json, os, re, sys, time, hashlib
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
OUT = ROOT / "out"

# ------------------------------------------------------------------ vocabulary

# voice: the kind's default, chosen by measured A/B (HANDOFF.md, voice); a brief may name another id
KINDS = {
    "webshow":   dict(keywords=["gita","shloka","mahabharata","episode","chapter","verse","dharma","krishna","arjuna","namo"], ratio="16:9", runtime="mg", style="namo-vedic-ink", emotion="deadpan", voice="hi-IN-Chirp3-HD-Charon"),
    "explainer": dict(keywords=["explain","explainer","how","why","what is","tutorial","guide","walkthrough","deep dive"], ratio="16:9", runtime="rd", style="flat-motion-graphics", emotion="energetic", voice="hi-IN-Chirp3-HD-Kore"),
    "customer":  dict(keywords=["ad","promo","campaign","brand","client","launch","commercial","product"], ratio="16:9", runtime="mg", style="clean-professional", emotion="calm", voice="en_US-lessac-medium"),
    "shot-test": dict(keywords=["test","probe","smoke"], ratio="16:9", runtime="mg", style="minimalist-diagram", emotion="deadpan", voice="en_US-lessac-medium"),
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

RATIOS = ("16:9", "9:16", "1:1")
DURATION = re.compile(r"\b(\d{1,2}):(\d{2})\b|\b(\d+)\s*(?:(s\b|sec|second)|m\b|min|minute)", re.I)

def read_seconds(text, default=30):
    """The FIRST duration token in the brief is the film length: '40 second', '2 min', '1:30'.
    A ratio ('9:16') is never a duration."""
    for m in DURATION.finditer(text):
        if m.group(1):
            if m.group(0) in RATIOS: continue
            return int(m.group(1)) * 60 + int(m.group(2))
        return int(m.group(3)) * (1 if m.group(4) else 60)
    return default

def has_word(text, words):
    """Whole-word hits (a trailing plural 's' allowed): 'how' never matches 'show'."""
    return sum(1 for w in words if re.search(r"\b%ss?\b" % re.escape(w), text, re.I))

def read_ratio(text):
    if has_word(text, ["vertical", "9:16", "reel", "shorts", "tiktok", "story"]): return "9:16"
    if has_word(text, ["square", "1:1", "instagram"]): return "1:1"
    return "16:9"

def read_emotion(text):
    for e, words in {
        "energetic": ["energetic","punchy","hype","fast","excited","upbeat"],
        "dramatic":  ["dramatic","cinematic","epic","serious","sombre","slow"],
        "calm":      ["calm","professional","corporate","clean","soothing"],
        "deadpan":   ["deadpan","flat","matter of fact","dry"],
    }.items():
        if has_word(text, words): return e
    return None

def classify(text):
    best, score = "explainer", 0
    for kind, spec in KINDS.items():
        s = has_word(text, spec["keywords"])
        if s > score: best, score = kind, s
    return best, score

def declared_kind(scene):
    """The kind a scene declares for itself (rd beats file or mg scene.json), or None."""
    for f in (NAMO / "rd" / "beats" / f"{scene}.json", NAMO / "mg" / "scenes" / scene / "scene.json"):
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8")).get("kind")
    return None

def plan(brief):
    if isinstance(brief, str): brief = {"prompt": brief}
    def given(k, fallback):
        """Structured fields win; a supplied 0 is a value (the engine gate judges it), not absence."""
        v = brief.get(k)
        return fallback if v is None else v
    text = brief.get("prompt", "")
    # `key=value` selectors pick, they do not describe: keep them out of classification
    # ("scene=gita-1-1" would add a webshow 'gita' hit)
    sel = dict(re.findall(r"\b(\w+)=([\w.-]+)", text))
    prose = re.sub(r"\b\w+=[\w.-]+", " ", text)
    scene = given("scene", sel.get("scene"))
    kind, hit = classify(prose)
    declared = declared_kind(scene) if scene else None
    if brief.get("kind") is not None:
        if brief["kind"] not in KINDS:
            raise ValueError("brief kind %r is not one of %s" % (brief["kind"], ", ".join(KINDS)))
        kind, why_kind = brief["kind"], "brief sets kind"
    elif declared in KINDS:          # a named scene's own kind beats keyword guessing
        kind, why_kind = declared, f"scene {scene} declares {declared}"
    else:
        why_kind = f"{hit} keyword hit(s)" if hit else "no keyword hit, defaulted to explainer"
    spec = KINDS[kind]
    seconds = int(given("seconds", read_seconds(prose)))
    ratio = given("ratio", read_ratio(prose))
    emotion = given("emotion", read_emotion(prose) or spec["emotion"])
    style = given("style", spec["style"])
    voice = EMOTION_VOICE[emotion]
    vid = given("voice", spec["voice"])
    look = STYLE_LOOK.get(style, STYLE_LOOK["minimalist-diagram"])
    return {
        "prompt": text,
        "kind": kind,
        "kind_confidence": hit,
        "runtime": given("runtime", spec["runtime"]),
        "scene": scene,     # mg: namo/mg/scenes/<scene>/, rd: namo/rd/beats/<scene>.json
        "style": style,
        "look": look,
        "seconds": seconds,
        "ratio": ratio,
        "fps": int(given("fps", 30 if kind != "webshow" else 24)),
        "emotion": emotion,
        "voice": {
            "engine": "chirp3" if "-Chirp3-HD-" in vid else "piper",
            "id": vid,
            **voice,
        },
        "bed": brief.get("bed"),     # namo/audio/<bed>.flac, ducked under the voice; none unless asked
        "chapters": kind in ("explainer",),
        "budget_usd": float(given("budget_usd", 0.0)),
        "decision": {
            "why_kind": why_kind,
            "why_runtime": "CPU motion graphics are free and deterministic",
        },
    }

# ------------------------------------------------------------------ run

def step(msg): print(f"[agent] {msg}", flush=True)

SCENE_FOR_KIND = {
    # a kind maps to a scene only when that scene actually exists for it.
    # gita-ep01 is a webshow scene. An explainer is one beats file per topic, so it has no
    # default: the brief names it (scene=<beats name>), or the job is refused.
    "webshow": "gita-ep01",
}

def SCENES_AVAILABLE():
    """mg scene dirs and rd beats files: the names a job's `scene` may take."""
    d, beats = NAMO / "mg" / "scenes", NAMO / "rd" / "beats"
    return ({x.name for x in d.iterdir() if x.is_dir()} if d.exists() else set()) | \
           ({x.stem for x in beats.glob("*.json")} if beats.exists() else set())

def render(p):
    """Hand the plan to the engine. The engine owns the renderers; the agent owns the decision."""
    sys.path.insert(0, str(NAMO))
    import importlib
    engine = importlib.import_module("engine")

    scenario = p.get("scene") or SCENE_FOR_KIND.get(p["kind"])
    if not scenario:
        # An honest refusal beats a wrong film. If the brief asks for a kind that has no
        # authored scene yet, say so and name the fix; never render another kind's scene.
        have = ", ".join(sorted(SCENES_AVAILABLE())) or "none"
        return {"ok": False,
                "error": f"no scene authored for kind '{p['kind']}'. "
                         f"scenes on disk: {have}. Add namo/mg/scenes/<name>/ or namo/rd/beats/<name>.json, "
                         f"or pass scene=<name>."}
    # SPEC §2: a job must carry the whole decision, not a subset. The engine refuses a
    # partial job before rendering, which is why every run used to fail with no reason.
    job = {
        "schema": "namo.job/1",
        "kind": p["kind"],
        "runtime": p["runtime"],
        "scene": scenario,
        "seconds": p["seconds"],
        "fps": p["fps"],
        "ratio": p["ratio"],
        "style": p["style"],
        "emotion": p["emotion"],
        "voice": p["voice"],
        **({"bed": p["bed"]} if p.get("bed") else {}),
        "name": f"{p['kind']}-{scenario}",
        "workers": min(6, os.cpu_count() or 2),   # one browser per core; 4 on a 2-core runner thrashed (~40 min / 60 s)
    }
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
        return {"ok": False, "error": res.get("error") or "render failed", "log": res.get("log", "")[-1500:]}
    good, msg = engine.verify_video(res["out"], p["seconds"], p["voice"], res.get("voice"))
    return {"ok": good, "out": res.get("out"), "guard": msg, "audio": res.get("audio"), "error": None if good else msg}

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
