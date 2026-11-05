#!/usr/bin/env python3
"""
namo/jev.py - code review by constraint, not by prose.

Measured problem this solves: asking a model to "list all contradictions" makes it reason
indefinitely and return nothing. Asking it to pick from a fixed schema makes it answer in one
batched pass, every time, in about 700 ms on CPU.

llama.cpp's parallel-decision scores each field's allowed values as token paths forking from
one KV cache, so all fields are answered in a single decode and the model never writes prose.
The JSON is assembled by code, so it always matches the schema.

    python namo/jev.py --check
    python namo/jev.py --review namo/engine.py
    python namo/jev.py --review namo/engine.py --json
"""
import json, os, re, sys, urllib.request
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
JEV = os.environ.get("NAMO_JEV", "http://127.0.0.1:8096/v1/decision")
MODEL = os.environ.get("NAMO_JEV_MODEL", "q")

RULES = {
    "bare_except_pass": "Does any except block return a pass or success value instead of a failure?",
    "check_disabled": "Is any validation check disabled, bypassed, or allowed to fail open?",
    "silent_ignore": "Does the code accept an input and then never use it?",
    "stale_output": "Can a file from a previous run be treated as this run's output?",
    "unvalidated_input": "Is an external input used in a path or a shell command without validation?",
    "dead_branch": "Is there a branch that can never be reached?",
}

SCHEMA = {k: {"type": "boolean", "description": v} for k, v in RULES.items()}
SCHEMA["severity"] = {"type": "enum", "choices": ["blocking", "minor", "none"],
                      "description": "How bad is the worst problem?"}

INSTRUCTIONS = ("You are reviewing one python function against a fixed list of questions. "
                "Answer each question about the code, not about the documentation. "
                "A question is true only if the code itself does it.")


def post(path, body, timeout=120):
    req = urllib.request.Request(path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.loads(f.read())


def health():
    base = JEV.rsplit("/v1/", 1)[0]
    try:
        with urllib.request.urlopen(base + "/health", timeout=10) as f:
            return f.status == 200
    except Exception:
        return False


def functions(path):
    """Split a python file into function chunks: one context is one function."""
    try:
        src = Path(path).read_text(errors="ignore")
    except Exception:
        return []
    out, cur, name, indent = [], None, None, None
    for line in src.splitlines():
        m = re.match(r"^(\s*)def (\w+)\(", line)
        if m and (indent is None or len(m.group(1)) <= indent):
            if cur:
                out.append((name, "\n".join(cur)))
            name, cur, indent = m.group(2), [line], len(m.group(1))
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped and len(line) - len(line.lstrip()) <= indent and not stripped.startswith(("%", ")")):
            out.append((name, "\n".join(cur)))
            cur = None
        else:
            cur.append(line)
    if cur:
        out.append((name, "\n".join(cur)))
    return [(n, c) for n, c in out if len(c.strip()) > 40]


def review(path, max_functions=24):
    fns = functions(path)[:max_functions]
    if not fns:
        return {"error": "no functions found in " + str(path)}
    if not health():
        return {"error": "jev server not up at " + JEV}
    body = {"model": MODEL, "instructions": INSTRUCTIONS, "schema": SCHEMA,
            "contexts": [c for _, c in fns]}
    d = post(JEV, body, timeout=300)
    hits = []
    for (name, _), res in zip(fns, d.get("results", [])):
        dec = res.get("decision", {})
        bad = [k for k, v in dec.items() if k != "severity" and v is True]
        if bad:
            hits.append({"function": name, "flags": bad, "severity": dec.get("severity"),
                         "prob": {k: round(res["fields"][k]["probability"], 3) for k in bad}})
    return {"file": str(path), "functions": len(fns), "flagged": hits,
            "timing": d.get("timings", {}), "usage": d.get("usage", {})}


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--check":
        print("server up:", health())
        print("model:", MODEL)
        print("schema fields:", ", ".join(SCHEMA))
        return 0
    if argv[0] == "--review":
        r = review(argv[1])
        if "--json" in argv:
            print(json.dumps(r, indent=1))
            return 0
        if r.get("error"):
            print("ERROR:", r["error"])
            return 1
        print("%s: %d functions" % (r["file"], r["functions"]))
        if not r["flagged"]:
            print("  no flags")
        for h in r["flagged"]:
            print("  %-28s %-14s %s" % (h["function"], h["severity"], ", ".join(h["flags"])))
        t = r.get("timing", {})
        print("  %sms per decision, %s contexts" % (t.get("per_decision_ms"), r["usage"].get("context_tokens")))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
