#!/usr/bin/env python3
"""
namo/egm.py — the Elephant-Goldfish loop, running on the phone's local proxy.

This is the real EGM protocol, not a lint pass:
  - GOLDFISH runs with NO conversation history. It sees only files on disk. It cannot
    know what the author intended, so it cannot forgive an unstated assumption.
  - ELEPHANT holds the context (the review history, the spec, the decisions) and is the
    only one allowed to write code.
  - The loop repeats until the goldfish stops finding blockers, or the round limit hits.

Why the split matters: the same model that wrote the code will defend it. A fresh-context
reviewer does not know there is anything to defend.

    python namo/egm.py --rounds 3
    python namo/egm.py --review-only
    python namo/egm.py --apply            # actually write the elephant's patches

Needs the local proxy on 127.0.0.1:8322. The proxy is phone-local; CI cannot reach it.
"""
import json, os, re, sys, time, shutil, subprocess
from pathlib import Path
import urllib.request

NAMO = Path(__file__).resolve().parent
ROOT = NAMO.parent
PROXY = "http://127.0.0.1:8322/v1/chat/completions"
KEY = "zafiro-local-key"
MODEL = os.environ.get("EGM_MODEL", "claude-opus-5-5")

# what the reviewer and the fixer are both allowed to read
CORPUS_GLOBS = ["SPEC.md", "README.md", "queue.json", "namo/*.py", "namo/*.sh",
                "pipeline_defs/namo-*.yaml", ".github/workflows/*.yml"]

GOLDFISH = """You are a Goldfish reviewer in the Elephant-Goldfish Model (EGM).

You have NO conversation history and no knowledge of author intent. You get only the files
below: a design document (SPEC.md), a README, and the source claiming to implement them.

Find what is actually broken, assuming nothing. Every finding names a file and a concrete
behaviour. No praise. No restating the spec. Classify each finding:
  CONTRADICTION (doc says X, code does Y)
  SILENT ASSUMPTION (code depends on something never written)
  HOLE (doc requires something never implemented)
Rank by whether it stops a correct video from being produced.

Output exactly:
## BLOCKERS
## SILENT ASSUMPTIONS
## HOLES
## CHALLENGES TO THE SPEC
## VERDICT
"""

ELEPHANT = """You are the Elephant in the Elephant-Goldfish Model (EGM).

You hold the full context: this is the NAMO video studio engine. It must turn a one-line
brief into a correct video. A fresh-context goldfish reviewer has listed blockers. Your job
is to fix them in code, honestly.

Rules that override any instinct to look productive:
1. If a fix is not possible without a decision only the owner can make (a licence, a key, a
   credential, a product choice), DO NOT fake it. Write the refusal in code and list it under
   UNFIXABLE with the exact question to ask.
2. If a fix requires deleting or bypassing a check, that is not a fix. Say so instead.
3. Do not add files. Edit the ones that exist. Smallest complete change.
4. Plain English in comments. No marketing words.
5. Every patch must name the finding it closes.

Output format, strictly:

### PATCH <path>
```python
<the complete new contents of that file>
```

(repeat per file)

### UNFIXABLE
- <finding> -> <the exact question to ask the owner>

### CLOSED
- <finding number/name> -> what changed
"""

def build_corpus():
    parts = []
    for pat in CORPUS_GLOBS:
        for p in sorted(ROOT.glob(pat)):
            if p.is_file() and "reviews/" not in str(p):
                parts.append(f"\n\n===== FILE: {p.relative_to(ROOT)} =====\n{p.read_text(errors='ignore')}")
    return "".join(parts)

def call(system, user, max_tokens=16000, timeout=300):
    body = {"model": MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    req = urllib.request.Request(PROXY, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        d = json.loads(f.read())
    return d["choices"][0]["message"].get("content") or "", d.get("usage", {})

def blockers(review):
    m = re.search(r"##\s*BLOCKERS(.*?)(?=\n##|\Z)", review, re.S | re.I)
    if not m: return 0, []
    body = m.group(1).strip()
    n = len(re.findall(r"^\s*\d+[.)]\s", body, re.M)) or (1 if body and "none" not in body.lower() else 0)
    return n, body

def apply_patches(text, dry=True):
    written, rejected = [], []
    for m in re.finditer(r"###\s*PATCH\s+(\S+)\s*\n+```(?:python|bash|yaml|yml|json)?\n(.*?)```", text, re.S):
        rel, code = m.group(1).strip(), m.group(2)
        target = (ROOT / rel).resolve()
        if not str(target).startswith(str(ROOT)) or not target.exists():
            rejected.append((rel, "not an existing file inside the repo")); continue
        if dry:
            written.append((rel, len(code))); continue
        shutil.copy(target, str(target) + ".bak")
        target.write_text(code)
        written.append((rel, len(code)))
    return written, rejected

def main():
    rounds = 3
    args = sys.argv[1:]
    if "--rounds" in args: rounds = int(args[args.index("--rounds") + 1])
    dry = "--apply" not in args
    review_dir = ROOT / "reviews"; review_dir.mkdir(exist_ok=True)

    for r in range(1, rounds + 1):
        print(f"\n=== round {r} ===")
        corpus = build_corpus()
        print(f"corpus {len(corpus)} chars")

        print("goldfish (fresh context) ...")
        rev, u1 = call(GOLDFISH, "Here is everything you have:\n" + corpus)
        (review_dir / f"goldfish-r{r}.md").write_text(rev)
        n, body = blockers(rev)
        print(f"  {n} blockers, {u1.get('completion_tokens')} tokens")
        if n == 0:
            print("  goldfish is clean — loop ends"); break

        print("elephant (holds context) ...")
        fix, u2 = call(ELEPHANT,
            f"SPEC.md and the code are in the corpus below.\n\n"
            f"GOLDFISH BLOCKERS:\n{body}\n\nFull corpus:\n{corpus}")
        (review_dir / f"elephant-r{r}.md").write_text(fix)
        written, rejected = apply_patches(fix, dry=dry)
        print(f"  patches: {len(written)} {'(dry)' if dry else 'applied'}")
        for w in written: print("   ", w)
        for w in rejected: print("    REJECTED", w)
        unfixable = re.search(r"###\s*UNFIXABLE(.*?)(?=\n###|\Z)", fix, re.S)
        if unfixable:
            print("  UNFIXABLE (needs the owner):")
            for line in unfixable.group(1).strip().split("\n")[:12]:
                if line.strip(): print("   ", line.strip()[:160])
        if dry: print("  dry run — rerun with --apply to write"); break

    return 0

if __name__ == "__main__":
    sys.exit(main())
