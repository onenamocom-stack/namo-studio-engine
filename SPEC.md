# SPEC — NAMO Studio Engine

**Status:** living document. EGM (elephant-goldfish) owns it.
**Rule:** a change to code that is not in this spec is drift. `namo/drift.py` fails the run.

---

## What this system is

One engine that makes videos from a brief. It is **not** a collection of renderers; it is
**one contract** with several interchangeable runtimes behind it.

```
brief (text) -> agent.py (router) -> plan.json -> engine.py (runtime) -> stems -> compose -> film.mp4
                                          |                                |
                                          +-> why_kind, why_runtime        +-> verify_video()
```

Nothing downstream re-decides what upstream decided. If a decision cannot be carried to the
renderer, the decision does not exist.

---

## 1. Brief contract

Input is a natural-language string, or a JSON object with the same keys. The router derives,
deterministically, with no model and no network:

`kind`, `runtime`, `style`, `seconds`, `ratio`, `fps`, `emotion`, `voice`.

**Invariant B1:** the same brief yields the same plan, on any machine, forever.

Measured behaviour (this is the test table; `namo/drift.py` runs it):

| brief | kind | runtime | style | seconds | ratio | emotion |
|---|---|---|---|---|---|---|
| "30 second explainer about Jev mode" | explainer | rd | flat-motion-graphics | 30 | 16:9 | energetic |
| "40 sec vertical reel about jewellery" | explainer | rd | flat-motion-graphics | 40 | 9:16 | energetic |
| "gita chapter 2 episode 3, 60 seconds" | webshow | mg | namo-vedic-ink | 60 | 16:9 | deadpan |
| "2 min dramatic cinematic promo" | customer | mg | clean-professional | 120 | 16:9 | dramatic |
| "5 second test" | shot-test | mg | minimalist-diagram | 5 | 16:9 | deadpan |

Determinism rules (each was a real bug):
- Durations are parsed from the **first** duration-like token only, and a ratio (`9:16`,
  `1:1`, `16:9`) is never read as a duration.
- Explicit overrides in the JSON form always win over anything parsed from the prompt.
- Keyword matching is word-boundary, not substring: "how" must not match "show".

---

## 2. Job contract — what a runtime actually receives

This section did not exist before, which is why the renderer never saw the plan. It exists now.

A **job** is a JSON object. Every key is required unless marked optional. `engine.py` refuses
a job that is missing a required key, before any renderer is called.

```json
{
  "schema": "namo.job/1",
  "kind":     "webshow | explainer | customer | shot-test",
  "runtime":  "mg | h3 | rd",
  "scene":    "gita-ep01",
  "seconds":  60,
  "fps":      24,
  "ratio":    "16:9 | 9:16 | 1:1",
  "style":    "namo-vedic-ink",
  "emotion":  "calm | energetic | dramatic | deadpan",
  "voice":    {"engine": "piper", "id": "hi_IN-pratham-medium", "rate": 1.0},
  "name":     "gita-ep01",
  "workers":  4
}
```

- `seconds` is **required and must be > 0**. A film without a target length cannot be verified,
  so it is not requested.
- `kind` is **required**. An untyped job may not render: that is how the wrong film gets made.
- `scene` must be a plain directory name inside `namo/mg/scenes/`.
- `name` is sanitised to `[A-Za-z0-9._-]` before it is used in a path.
- `workers` is optional, default 4.

**Every plan field must reach the renderer.** A renderer that ignores `seconds`, `ratio` or
`style` is not implementing this contract; it is rendering whatever the scene file says.

The `mg` runtime carries the plan to the page through lemo's own channels: `--q` becomes the
URL query (`?seconds=&ratio=&style=&emotion=&kind=&authoredSeconds=&authoredRatio=`), `--size`
becomes the frame size for that ratio, and `render.json` sits at the scene root as a second copy.

**What this does and does not guarantee — stated plainly:**

- The plan *is delivered*. A scene that reads `location.search` can honour any brief.
- The engine cannot prove the scene reads it. So the engine does not pretend to: it renders,
  and §4 judges the result. A scene that ignores the query produces a film at its authored
  length; §4 rejects it. That rejection is the enforcement point, not a refusal up front.
- A scene **opts in** by declaring `"applicable": true` in `scene.json`. A scene without it is
  still renderable but is treated as fixed-format; a brief that differs will fail §4, loudly.

This is the honest split: the engine guarantees delivery and judgement, the scene guarantees
application. Making the engine refuse every mismatch would have meant the renderer never saw a
new value at all — that was the hole goldfish round 7 named, and it is why the veto is gone.

---

## 3. Runtime contract

A runtime is a class with `name`, `kind`, `cost_per_sec_usd`, `max_seconds`, `probe()`,
`render(job, outdir)` and optionally `produces`.

| runtime | kind | produces | cost | what it makes |
|---|---|---|---|---|
| `mg` | cpu | `film` | 0 | vector motion graphics through lemo |
| `h3` | gpu | `stems` | $0.00039/s | MiniMax H3 image-to-video clips, raw, per GPU_CONTRACT |
| `rd` | cpu | `film` | 0 | rendiv (React) motion-design explainers from `namo/rd/beats/<scene>.json` |

**Invariant R1:** a runtime enters `REGISTRY` only if `probe()` proves it works.
`probe()` must exercise the thing, not merely observe that files exist:

- `mg.probe()` checks lemo, node, chrome, **ffmpeg and ffprobe**, and that a scene exists.
- `h3.probe()` makes one authenticated call to the provider and fails on a non-200.
- `rd.probe()` renders one second of a beats file at 320x180 and makes the voice speak.

**Invariant R2:** `engine.REGISTRY` is the only door. No pipeline, workflow or script calls a
renderer directly. `REGISTRY` is populated at import, so any importer sees the same runtimes.

`h3` produces **stems, not a film**. `render()` returns `{"ok", "kind": "stems", "stems": [...]}`.
The CLI prints `STEMS OK` and exits 0; it must **not** claim a film passed.

---

## 4. Output contract — when a film is accepted

A render is accepted only if `verify_video()` passes. All of these are hard:

| check | rule | why |
|---|---|---|
| exists | file present | |
| size | **> 20480 bytes** | a stub is not a film |
| decodable | `ffprobe` returns a duration | |
| duration | `abs(dur - seconds) <= max(0.5, seconds * 0.02)` | a 57 s film is not a 60 s film |
| duration target | `seconds > 0` or refuse | cannot verify without a target |
| pixels | blank frames <= 0 % | sampled at 1 fps, 64x36, luma stddev < 1.0 is blank |

**Invariant O1:** "the file exists" is never success.
**Invariant O2:** a failure to run a check is a failure. No `except: return True`. If `ffmpeg`,
`ffprobe` or the pixel sampler is unavailable, the film is **rejected**, not passed.
**Invariant O3:** a stale file never satisfies a run. The output path is deleted before render.

---

## 5. Pipeline contract

A pipeline YAML declares stages; each stage names a skill that must exist at
`skills/<name>.md`.

**Invariant P1:** a pipeline naming a skill with no file is **invalid** and must not run.
`engine.check_pipeline(path)` is the enforcement point and returns the missing skills.
Skill names are matched whether quoted or bare, and comments are ignored.

The pipeline loader calls `check_pipeline()` before any stage executes. D1–D3 are exactly the
case this refuses today.

---

## 6. Renderer honesty

The renderer receives the job. If it does not apply `seconds`, `ratio` or `style`, the film
cannot match the brief and that is a **blocker**, not a limitation.

When a runtime cannot honour a job field, it must refuse the job with a named reason. Rendering
a film that silently ignores the brief is the worst possible outcome, because it looks like
success.

---

## Known drift (measured, updated by each goldfish round)

| # | where | what | severity |
|---|---|---|---|
| D1 | `namo-webshow.yaml` | **closed 6 Nov**: the 8 skills exist under `skills/pipelines/namo/` | closed |
| D2 | `namo-customer.yaml` | **closed 6 Nov**: the 9 skills exist under `skills/pipelines/customer/` | closed |
| D3 | `namo-explainer.yaml` | **closed 6 Nov**: `pipelines/explainer/beat-director` written, stage repointed | closed |
| D4 | `agent.py` | a brief with no authored scene is refused rather than mis-rendered — honest, but no film | blocks non-webshow |
| D5 | R2 creds | keys return 401 | publish blocked |
| D6a | `mg` renderer | **closed**: the plan reaches the page (`--q`, `--size`, `render.json`); §4 judges the result. Delivery is guaranteed. | closed |
| D6b | `mg` scenes | **closed 6 Nov for `gita-ep01`**: the scene reads `seconds` (20–180) and `ratio` from `location.search`. A new scene must do the same before it sets `applicable: true`. | closed |
| D7 | pipelines | no loader exists, so P1 is checked only when called by hand | blocks P1 enforcement |

D6 is the one that matters most: the router decides, and the renderer ignores the decision.

---

## Definition of done

- [ ] `python3 namo/engine.py probe` exits 0
- [ ] every row of the brief table reproduces exactly (drift.py runs it)
- [ ] a job missing `seconds` or `kind` is refused before any render
- [ ] a film is rejected if its duration differs from `seconds` by more than 2 %
- [ ] a blank film is rejected, and a missing ffmpeg is a rejection, not a pass
- [ ] `check_pipeline()` refuses D1–D3
- [x] the renderer is *given* `seconds`/`ratio`/`style` (D6a: `--q` + `--size` + `render.json`)
- [ ] at least one scene **applies** them by reading `location.search` (D6b)

Until every box is ticked the studio is being built, not finished.
