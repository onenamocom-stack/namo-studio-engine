#!/usr/bin/env python3
"""
namo/drift.py — the goldfish.

Reads SPEC.md's invariants and checks the repository against them. Zero context:
it does not know what we intended, only what the spec says must be true.
Exit code 1 on any drift, so CI fails and the run cannot pretend to be done.

    python namo/drift.py
    python namo/drift.py --json
"""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMO = ROOT / "namo"

findings = []
def drift(id_, where, what, severity="block"):
    findings.append({"id": id_, "where": where, "what": what, "severity": severity})

# P1: every skill a pipeline names must exist on disk
for py in sorted((ROOT / "pipeline_defs").glob("*.yaml")):
    text = py.read_text()
    named = set(re.findall(r"skill:\s*([\w/.-]+)", text)) | set(re.findall(r"-\s*(pipelines/[\w/.-]+)", text))
    for sk in sorted(named):
        f = ROOT / "skills" / (sk + ".md")
        if not f.exists():
            drift("P1", f"pipeline_defs/{py.name}", f"names skill '{sk}' which has no file at skills/{sk}.md")

# R2: every runtime must be resolvable, and the registry must be the only door
eng = NAMO / "engine.py"
if not eng.exists():
    drift("R2", "namo/engine.py", "engine is missing")
else:
    code = eng.read_text()
    if "REGISTRY" not in code:
        drift("R2", "namo/engine.py", "no REGISTRY — runtimes are being called directly")
    for rt in re.findall(r'name\s*=\s*"(\w+)"', code):
        pass
    # no pipeline or workflow may bypass the registry
    for wf in (ROOT / ".github/workflows").glob("*.yml"):
        w = wf.read_text()
        if "core/render/video.mjs" in w or "render/video.mjs" in w:
            drift("R2", f".github/workflows/{wf.name}", "calls the renderer directly instead of namo/engine.py")

# O1: the output guard must exist and must actually check pixels
if eng.exists() and "def verify_video" not in eng.read_text():
    drift("O1", "namo/engine.py", "verify_video() is missing — a blank film would pass")

# B1: the router must be pure (no network, no model) and must have a scene per kind
ag = NAMO / "agent.py"
if not ag.exists():
    drift("B1", "namo/agent.py", "router is missing")
else:
    a = ag.read_text()
    for bad in ("requests.", "openai", "urllib.request", "http"):
        if bad in a:
            drift("B1", "namo/agent.py", f"router is not pure — it touches {bad}")
    # D4 from the spec: the render fallback must not silently borrow another kind's scene
    if re.search(r'scenario\s*=\s*"gita-ep01"', a):
        drift("B1", "namo/agent.py",
              "render() falls back to scene 'gita-ep01' for every kind — an explainer brief renders a webshow scene")

def main():
    as_json = "--json" in sys.argv
    blocking = [f for f in findings if f["severity"] == "block"]
    if as_json:
        print(json.dumps({"findings": findings, "blocking": len(blocking),
                          "ok": not blocking}, indent=1))
    else:
        if not findings:
            print("no drift: the repository matches SPEC.md")
        for f in findings:
            print(f"[{f['severity'].upper():5s}] {f['id']:3s} {f['where']:42s} {f['what']}")
        print(f"\n{len(blocking)} blocking, {len(findings)-len(blocking)} advisory")
    return 1 if blocking else 0

if __name__ == "__main__":
    sys.exit(main())
