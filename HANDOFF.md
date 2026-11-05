# NAMO Studio — handoff for a fresh agent

You are taking over a video-production engine. Read this once, then work. It is written so
that you do not need any conversation history.

Repository: **github.com/onenamocom-stack/namo-studio-engine**
(older, still useful: `onenamocom-stack/namo-studio` — holds the manufacture contracts and
the piper/ffmpeg CPU workflow. The engine repo is the one being built now.)

---

## 1. What the thing is supposed to do

One line in, one video out.

```
brief text -> namo/agent.py (router, deterministic) -> plan
plan       -> namo/engine.py (runtime: mg | h3)      -> film or stems
film       -> namo/engine.py verify_video()          -> accept or reject
queue      -> namo/factory.py                        -> runs all of the above, unattended
```

Three pipelines are declared: `namo-webshow` (Mahabharata/Gita episodes), `namo-explainer`
(long-form teaching videos), `namo-customer` (client work). Only the router and the engine
exist in code; the pipelines are YAML contracts whose skill files are mostly missing.

---

## 2. How to run it

### On a GitHub Actions runner (the normal path)
```
Actions -> "namo-agent" -> Run workflow -> paste one line -> watch the artifact
Actions -> "factory"    -> (also runs every 6 hours) -> reads queue.json -> makes it
```
Both workflows bootstrap the engines themselves (`namo/bootstrap.sh`), which clones:
- `ftm/` — imserhatdemir/ft-motion (MIT). It vendors **lemo-opuscar** (68 vector styles) at
  `ftm/lemo/`, and carries `animation/` — a p5 + p5.brush character kit with 11 mocap clips
  and spring-physics easing. **This is where "emotion" comes from, in code.**
- `lemo/` — the engine on its own, for pipelines that do not want the wrapper.

Runner notes that cost time before, do not relearn them:
- Use the runner's `google-chrome`. Do not `apt install chromium`: it pulls snap and adds
  ~5 minutes to every run.
- The engines are cached on `namo/bootstrap.sh`'s hash.
- `PLAYWRIGHT_CHROME` must be exported; rendering is Playwright-driven.

### On the phone (only for the EGM loop, see section 5)
```bash
cd /data/user/0/com.niki914.zafiro/files/egm_run
EGM_MODEL=claude-opus-5-5 python3 namo/egm.py --review      # review only
python3 namo/engine.py probe                                 # what is ready
python3 namo/engine.py render job.json out                   # one render
```

---

## 3. The contracts (SPEC.md is the authority; this is the summary)

- **§1 Brief** — router derives kind/runtime/style/seconds/ratio/fps/emotion/voice. Same brief
  must yield the same plan, forever. No model, no network.
- **§2 Job** — `namo.job/1`. Required: schema, kind, runtime, scene, seconds, fps, ratio,
  style, emotion, voice, name. `engine.validate_job()` refuses anything incomplete **before**
  a renderer runs.
- **§3 Runtime** — a runtime enters `engine.REGISTRY` only if `probe()` proves it works.
  `mg` = CPU vector, produces a film. `h3` = GPU, produces **stems, not a film**.
- **§4 Output** — a film is accepted only if `verify_video()` passes: > 20480 bytes, ffprobe
  duration within 2 % of `seconds`, and **zero blank frames**. A failure to run a check is a
  rejection, never a pass.
- **§5 Pipeline** — a pipeline naming a skill with no file is refused by
  `engine.check_pipeline()`.

---

## 4. What is built, what is not — measured, not claimed

Built and verified:
- `namo/agent.py` — the router. Its decision table is in SPEC §1 and was tested.
- `namo/engine.py` — job gate, runtime registry, `verify_video()`, `check_pipeline()`.
- `namo/factory.py` — reads `queue.json`, plans, checks feasibility, renders, verifies,
  writes `status.json`. An infeasible job is marked BLOCKED **with the reason**.
- `namo/drift.py` — checks the repo against SPEC.md, fails CI.
- `.github/workflows/` — `namo-agent` (one prompt), `factory` (cron + dispatch), `drift`.
- `skills/egm/` — Google's Elephant-Goldfish Model skills (Apache-2.0).

Built 6 Nov (laptop OMP, after the phone went offline):
- **D6b closed** for `gita-ep01`: the scene applies `seconds` (20–180, story time-scaled) and `ratio`
  (16:9 / 9:16 / 1:1, cover-crop around each shot's subject) and exposes `window.VO`.
- **Voice**: piper (`hi_IN-pratham-medium`) speaks `window.VO`, placed at each line's time (≤1.15x
  speed-up, else the job fails), muxed with lemo `mux.sh`; `verify_video` requires a non-silent audio
  stream when the job has a voice. Devanagari font `NotoSerifDeva` (namo/mg/fonts.css, fetched by bootstrap).
- Explainer `beat-director` skill written; the explainer pipeline passes `check_pipeline`.

Not built (the actual backlog):
- **Explainer runtime**: the owner rejected the lemo ink look for explainers ("nowhere near Codacus").
  The explainer moves to `thecodacus/rendiv` (`namo/rd/`, in progress).
- 17 skill files referenced by `namo-webshow` and `namo-customer` do not exist (D1–D2).
- No pipeline loader: nothing reads `pipeline_defs/*.yaml` at runtime.
- R2 publish needs working credentials (`R2_AK/R2_SK/R2_EP` in repo secrets).

---

## 5. The EGM loop — how review works here

`namo/egm.py` runs the Elephant-Goldfish protocol against the **phone-local** proxy
(`127.0.0.1:8322`, CLIProxyAPI under proot, models from the owner's subscriptions). CI cannot
reach it, so this runs from the phone, not from Actions.

- **Goldfish** = one call with **no conversation history**, given a spec and 1-3 files. It
  cannot know author intent, so it cannot forgive an unstated assumption.
- **Elephant** = the same model with context, allowed to write code.
- The loop keeps a patch only if blockers strictly decrease; otherwise it reverts.

Budget rules that exist because they were violated: one document + at most three source files
per call (~20 KB), 3000 tokens for a review, 180 s timeout. A 54 KB corpus once produced a
23,000-token prompt and a timeout.

**If the proxy is down**, start it as the shell uid, not the app uid — the app uid cannot write
`/data/local/tmp/agent/cpa/`:
```bash
# as shizuku/shell:
cd /data/local/tmp/agent && nohup env LD_LIBRARY_PATH=$PWD/proot \
  PROOT_LOADER=$PWD/proot/loader PROOT_TMP_DIR=$PWD/tmp \
  SSL_CERT_FILE=$PWD/proot/ca-bundle.crt \
  $PWD/proot/proot -b $PWD/proot/resolv.conf:/etc/resolv.conf \
  $PWD/np/cli-proxy-api -config $PWD/cpa/config8322.yaml >> $PWD/cpa/proxy8322.log 2>&1 &
```
Key: `zafiro-local-key` (in `cpa/config8322.yaml`).

---

## 6. What has already been tried and rejected — do not repeat

- **Prompting a video with an LLM.** Not deterministic, not frame-exact, not cheap.
- **Jev/agentic browser as the renderer.** Interactive, ~2 s per frame, no determinism.
  Jev belongs in the *decision* layer, and that layer is already a deterministic router.
- **Manim / Remotion.** Remotion is free only ≤3 employees; Manim is math-specific.
- **`ft-motion` alone, `lemo` alone, `stillmotion`, `html-to-video-skill`.** `ft-motion` is the
  superset (it vendors lemo and adds the animation kit). The other two are minimal or
  redundant.
- **`thecodacus/rendiv`** — genuinely the tool behind the reference video's *style*, React +
  `useFrame()`, Apache-2.0, 22 packages. Not yet adopted; it is a candidate to replace `mg`
  later, not a fix for today.
- **OpenMontage (AGPL)** is the base for the 13 pipelines and 157 skills. The fork is
  `namo-studio-engine`.

---

## 7. Ground rules for whoever picks this up

1. **Never claim a film passed without `verify_video()` output.** A blank film once shipped
   as "success" because a file existed.
2. **Do not weaken a check to make a finding disappear.** If `verify_video` is too strict, fix
   the threshold; never `except: return True`.
3. **Do not create a second repo or a second tool.** Check what exists first; the owner has
   corrected this twice.
4. **A runtime that cannot honour the brief must refuse the job.** Rendering the wrong film is
   worse than rendering nothing.
5. **Run the goldfish before saying "done."** It has caught every real bug so far, including
   ones introduced by the fix for the previous bug.

---

## 8. Immediate next steps, in order

1. Explainer on rendiv at the Codacus bar, wired as a runtime with the same job/verify contract.
2. Write the 17 missing webshow/customer skill files (or cut the pipelines down to what exists).
3. Add the pipeline loader that calls `check_pipeline()`.
4. Restore R2 publish with fresh credentials.
