# SPEC — NAMO Studio Engine

**Status:** living document. EGM (elephant-goldfish) owns it.
**Rule:** a change to code that is not in this spec is drift. `egm-drift-report` fails the run.

---

## What this system is

One engine that makes videos from a brief. It is **not** a collection of renderers;
it is **one contract** with several interchangeable runtimes behind it.

```
brief (text)  ->  agent.py (router)  ->  plan.json  ->  engine.py (runtime)  ->  film.mp4
                                          |                                      |
                                          +-> why_kind, why_runtime              +-> verify_video()
```

Every stage has exactly one job, and nothing downstream re-decides what upstream decided.

---

## The four contracts

### 1. Brief contract
Input is a natural-language string. The router derives, deterministically:
`kind`, `runtime`, `style`, `seconds`, `ratio`, `fps`, `emotion`, `voice`.

Measured behaviour (tested 2026-11-05, 7/7):

| brief | kind | runtime | style | seconds | ratio | emotion |
|---|---|---|---|---|---|---|
| "30 second explainer about Jev mode" | explainer | mg | flat-motion-graphics | 30 | 16:9 | energetic |
| "40 sec vertical reel about jewellery" | explainer | mg | flat-motion-graphics | 40 | 9:16 | energetic |
| "gita chapter 2 episode 3, 60 seconds" | webshow | mg | namo-vedic-ink | 60 | 16:9 | deadpan |
| "2 min dramatic cinematic promo" | customer | mg | clean-professional | 120 | 16:9 | dramatic |
| "5 second test" | shot-test | mg | minimalist-diagram | 5 | 16:9 | deadpan |

**Invariant B1:** same brief => same plan. No model, no randomness, no network.

### 2. Runtime contract
A runtime is a class with `name`, `kind`, `probe()`, `render(job, outdir)`.

| runtime | kind | cost | what it makes |
|---|---|---|---|
| `mg` | cpu | ₹0 | vector motion graphics via lemo (68 styles) |
| `h3` | gpu | $0.00039/s | MiniMax H3 image-to-video, outsourced |

**Invariant R1:** a runtime is registered only if `probe()` can prove it works.
**Invariant R2:** no pipeline calls a renderer directly. Everything goes through `engine.REGISTRY`.

### 3. Output contract
A render is accepted only if `verify_video()` passes:

- file exists and is > 20 KB
- ffprobe duration >= `min_seconds`
- **luma variance**: sampled frames must not be flat

**Invariant O1:** "the file exists" is never success. This is the rule that would have
caught the blank gita-ep01 film.

### 4. Pipeline contract
A pipeline YAML declares `stages`, and each stage names a skill that **must exist on disk**
at `skills/<path>.md`.

**Invariant P1:** a pipeline whose skill files are missing is invalid and must not run.
(This is the current known failure: `namo-webshow` and `namo-customer` reference 17 skills
that do not exist. The pipeline loader must refuse them rather than silently no-op.)

---

## Known drift — measured, not assumed

| # | where | what | severity |
|---|---|---|---|
| D1 | `namo-webshow.yaml` | 8 skill paths missing | **blocks the pipeline** |
| D2 | `namo-customer.yaml` | 9 skill paths missing | **blocks the pipeline** |
| D3 | `namo-explainer.yaml` | `pipelines/namo/beat-director` missing | blocks that stage |
| D4 | `namo/agent.py` | `render()` falls back to scene `gita-ep01` for every kind | **wrong video for the brief** |
| D5 | R2 creds | `.config/cloudflare-r2.txt` keys return 401 | publish blocked |

D4 is the one that matters most: the router decides `explainer`, then renders a Gita scene.
The plan is right and the film is wrong. A router without a scene per kind is a lie.

---

## What "done" means

- [ ] `engine.py runtimes --probe` all READY
- [ ] `agent.py --dry "<brief>"` gives the plan from the table above
- [ ] `agent.py "<brief>"` produces a film that passes `verify_video()`
- [ ] the film actually matches the brief (a Jev explainer is not a Gita scene)
- [ ] every pipeline YAML has all its skill files
- [ ] R2 publish works

Until all six are true, the studio is not done. It is being built.
