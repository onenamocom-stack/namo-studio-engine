#!/usr/bin/env python3
"""
namo/egm.py — the Elephant-Goldfish loop, built to the budget in program.md.

Rebuild note: the first version fed 54 KB into one call, produced a 23,000-token prompt,
and timed out at 400 s. It also had no revert branch, so a bad patch would have been kept.
Both are fixed and enforced here, not merely commented.

Per round:
    review  -> GOLDFISH on one concern at a time (bounded corpus, 180 s, fresh context)
    patch   -> ELEPHANT with context, may write code
    verify  -> re-review with a fresh GOLDFISH
    decide  -> keep only if blockers strictly decreased, else revert

    python namo/egm.py --rounds 2 --dry
    python namo/egm.py --rounds 2 --apply
    python namo/egm.py --review

Requires the phone-local proxy on 127.0.0.1:8322. CI cannot reach it, by design.
"""
import json, os, re, shutil, sys, time, urllib.request
from pathlib import Path

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
PROXY = os.environ.get("EGM_PROXY", "http://127.0.0.1:8322/v1/chat/completions")
KEY = os.environ.get("EGM_KEY", "zafiro-local-key")
MODEL = os.environ.get("EGM_MODEL", "claude-opus-5-5")

# --- budget, from program.md. Do not raise these to make a run finish. ---
MAX_CORPUS = 20000
REVIEW_TOKENS = 3000
PATCH_TOKENS = 8000
TIMEOUT = 180

GOLDFISH = """You are a Goldfish reviewer in the Elephant-Goldfish Model.
You have no conversation history and no knowledge of author intent. You get one design
document and a few source files. Find where the code contradicts the document, and where it
depends on something nobody wrote down.

Every finding names a file and a concrete behaviour. No praise. No restating the spec.
Classify each: CONTRADICTION / SILENT ASSUMPTION / HOLE.
Rank by whether it stops a correct video from being produced.

Output exactly, and nothing else:
## BLOCKERS
1. <file> -> <what is wrong> -> <what it causes>
## SILENT ASSUMPTIONS
## HOLES
## VERDICT
<one sentence: can this pair of files produce a correct film from a one-line brief today?>
"""

ELEPHANT = """You are the Elephant in the Elephant-Goldfish Model. You hold the context and you may
write code. A fresh-context goldfish listed blockers. Fix them.

Bans (from program.md); any of these invalidates your patch:
- weakening or deleting a check to make a finding vanish
- adding a path that bypasses engine.REGISTRY
- editing SPEC.md, program.md, pipeline_defs/*.yaml, or the *_CONTRACT.json files
- claiming something works without evidence

If a fix needs a decision only the owner can make, do not fake it: put it under UNFIXABLE
with the exact question.

Output exactly:

### PATCH <relative/path.py>
```python
<complete new contents of that file>
```

### UNFIXABLE
- <finding> -> <question for the owner>

### CLOSED
- <finding> -> <what changed>
"""

def read(rel):
    p = ROOT / rel
    return p.read_text(errors="ignore") if p.exists() else ""

def call(system, user, max_tokens, timeout=TIMEOUT):
    body = {"model": MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(PROXY, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + KEY,
                                          "Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as f:
        d = json.loads(f.read())
    return (d["choices"][0]["message"].get("content") or "",
            d.get("usage", {}), round(time.time() - t0, 1))

def count_blockers(text):
    m = re.search(r"##\s*BLOCKERS(.*?)(?=\n##|\Z)", text, re.S | re.I)
    if not m:
        return 0
    body = m.group(1).strip()
    if not body or body.lower().startswith("none"):
        return 0
    return len(re.findall(r"^\s*\d+[.)]\s", body, re.M))

PASSES = [
    ("routing", "SPEC.md", ["namo/agent.py"]),
    ("engine",  "SPEC.md", ["namo/engine.py"]),
    ("factory", "SPEC.md", ["namo/factory.py", "namo/drift.py"]),
]

def review_pass(name, doc, files):
    corpus = "===== %s =====\n%s\n" % (doc, read(doc))
    for f in files:
        corpus += "\n===== %s =====\n%s\n" % (f, read(f))
    if len(corpus) > MAX_CORPUS:
        return None, {"pass": name, "error": "corpus %d > %d; split the pass" % (len(corpus), MAX_CORPUS)}
    text, usage, secs = call(GOLDFISH, corpus, REVIEW_TOKENS)
    return text, {"pass": name, "blockers": count_blockers(text), "chars": len(corpus),
                  "secs": secs, "tokens": usage.get("total_tokens")}

def full_review(round_dir):
    total, out = 0, {}
    for name, doc, files in PASSES:
        text, meta = review_pass(name, doc, files)
        if text is None:
            print("  %-8s SKIPPED: %s" % (name, meta["error"])); out[name] = meta; continue
        (round_dir / ("goldfish-%s.md" % name)).write_text(text)
        print("  %-8s %d blockers  %dc  %ss" % (name, meta["blockers"], meta["chars"], meta["secs"]))
        total += meta["blockers"]; out[name] = meta
    return total, out

GENESIS = ("SPEC.md", "program.md", "pipeline_defs/")

def apply_patches(text, workdir):
    touched = []
    for m in re.finditer(r"###\s*PATCH\s+(\S+)\s*\n+```[\w]*\n(.*?)```", text, re.S):
        rel, code = m.group(1).strip(), m.group(2)
        if any(g in rel for g in GENESIS):
            print("    REFUSED %s: GENESIS file" % rel); continue
        dst = workdir / rel
        if not dst.exists():
            print("    REFUSED %s: not an existing file" % rel); continue
        dst.write_text(code); touched.append(rel)
    return touched

def main():
    args = sys.argv[1:]
    rounds = int(args[args.index("--rounds") + 1]) if "--rounds" in args else 2
    apply = "--apply" in args
    review_only = "--review" in args

    stamp = time.strftime("%Y%m%dT%H%M")
    rev = ROOT / "reviews" / ("round-" + stamp)
    rev.mkdir(parents=True, exist_ok=True)

    print("egm: budget %dc / %ds / review %dt, model %s" % (MAX_CORPUS, TIMEOUT, REVIEW_TOKENS, MODEL))
    base, _ = full_review(rev)
    print("baseline: %d blockers" % base)
    if review_only or base == 0:
        return 0

    for r in range(1, rounds + 1):
        print("\n--- round %d ---" % r)
        work = ROOT / (".egm-work-%d" % r)
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ROOT / "namo", work / "namo")
        shutil.copy(ROOT / "SPEC.md", work / "SPEC.md")

        blocks = "\n".join((rev / ("goldfish-%s.md" % n)).read_text()
                           for n, _, _ in PASSES if (rev / ("goldfish-%s.md" % n)).exists())
        context = "SPEC.md\n%s\n\nprogram.md\n%s\n\nGOLDFISH BLOCKERS:\n%s" % (
            read("SPEC.md"), read("program.md"), blocks)
        if len(context) > MAX_CORPUS * 2:
            context = context[:MAX_CORPUS * 2]
        patch, usage, secs = call(ELEPHANT, context, PATCH_TOKENS)
        (rev / ("elephant-%d.md" % r)).write_text(patch)
        touched = apply_patches(patch, work)
        print("  elephant: %d patch(es) %ss %st -> %s" % (len(touched), secs, usage.get("total_tokens"), touched))
        unf = re.search(r"###\s*UNFIXABLE(.*?)(?=\n###|\Z)", patch, re.S)
        if unf and unf.group(1).strip():
            (rev / "unfixable.md").write_text(unf.group(1).strip())
            print("  UNFIXABLE: %s" % unf.group(1).strip()[:300])

        if not touched:
            print("  nothing applied; loop stops (an unparseable patch is not progress)"); break
        if not apply:
            print("  dry: patches staged in %s - rerun with --apply" % work); break

        saved = {}
        for rel in touched:
            live = ROOT / rel
            saved[rel] = live.read_text() if live.exists() else None
            live.write_text((work / rel).read_text())
        after, _ = full_review(rev)
        print("  verify: %d -> %d blockers" % (base, after))
        if after < base:
            print("  KEEP"); base = after
            if base == 0:
                break
        else:
            for rel, txt in saved.items():
                (ROOT / rel).write_text(txt if txt is not None else (work / rel).read_text())
            print("  REVERT (no strict improvement)"); break
    return 0

if __name__ == "__main__":
    sys.exit(main())
