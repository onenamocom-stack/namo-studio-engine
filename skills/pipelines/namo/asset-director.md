# Asset Director — NAMO Webshow Pipeline

## When to Use

You make every stem the episode needs (`pipeline_defs/namo-webshow.yaml`, stage `assets`) from the approved `scene_plan` and `script`, and prove each one is right by measurement. CPU work (ink-wash renders, voice) runs here on the runner. GPU work (MiniMax H3 shots) is never made through the engine: namo-studio makes it (`manufacture/namo_pod_run.py`, see namo-studio `FACTORY_MANUAL.md`) and publishes raw shots to R2 `render/<ep>/shots/`. **GPU returns shots; it never mixes, narrates, grades or concatenates.**

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `scene_plan` (`metadata.namo.shots[]`: runtime per shot), `script` (lines, measured timings) | What to make |
| Engine | `python namo/engine.py render <job.json>` — the only door to a runtime (SPEC R2); runtimes are `mg` (verified film) and `rd` only | Rendering |
| GPU shots | namo-studio `manufacture/namo_pod_run.py plans/<ep>.json` (rules in namo-studio `FACTORY_MANUAL.md`) | H3 shots, not made here |
| Tools | `tts_selector`, `image_selector`, `video_selector`, `music_gen` (yaml `tools_available`) | Keyframes, music |
| Voice | piper `hi_IN-pratham-medium` (`.voices/`) | Narration stems |

## Output Artifact: `asset_manifest`

One `assets[]` entry per file. Closed schema: per-file checks go in `metadata.namo`.

| Field | Content |
|-------|---------|
| `id` | `<SHOT>_video`, `<SHOT>_vo`, `<THEME>_s<SEED>`, … |
| `type` | `video` (H3 shot from namo-studio), `animation` (mg film/shot), `narration`, `music`, `sfx`, `image` (keyframe) |
| `path` | GPU: `render/<ep>/shots/<SHOT>.mp4` (R2); music: the score library `music/lib/<stem>.wav` (namo-studio `MUSIC_LIB.json`); mg: the engine's output film |
| `source_tool` | `engine.mg`, `namo-studio.h3`, `piper`, `music_gen`, `image_selector` |
| `scene_id` | Shot id |
| `model`, `seed`, `provider` | From the stem's `<SHOT>.json` meta (`graph`, `seed`, `gpu`) |
| `cost_usd` | Measured spend for that file (0 for CPU) |
| `duration_seconds`, `resolution`, `format` | Measured with ffprobe, not copied from the spec |
| `license` | H3: "MiniMax H3 output — commercial use must credit 'MiniMax H3' and disclose AI-generated content"; piper voice: the model card's licence; music: its model/source licence |
| `total_cost_usd` | Sum |
| `metadata.namo` | `{sha256sums: path, sha_verified: bool, checks: [{id, codec, pix_fmt, width, height, fps, frames, seconds, spec_seconds, yavg_max, ok}], music_checks: [{id, sample_rate, max_volume_db, mean_volume_db, ok}], pods_created: [ids], pods_alive_after: [], spend_usd}` |

## Process

### Step 1: Inventory and Estimate

List every stem the scene plan needs, grouped by runtime. CPU stems cost 0. H3 shots are namo-studio's spend, not this stage's: cost per episode = pod hours × the pod's price (RTX PRO 6000 ~$2.49/h; boot 9–19 min, ~80–110 s per shot turbo), never per second. If the H3 shots are not already in R2 `render/<ep>/shots/` and the estimate exceeds the showrunner's remaining budget, stop and report the numbers.

### Step 2: CPU Stems First (free)

1. **Ink-wash (`mg`)**: write the job (`namo.job/1`: `kind: webshow`, `runtime: mg`, `scene`, `seconds`, `fps: 24`, `ratio`, `style: namo-vedic-ink`, `voice`) and run `python namo/engine.py render job.json`. Only `PASS` (from `verify_video`: size, duration within 2 %, zero blank frames, audio not silent) counts.
2. **Narration**: one piper WAV per narrator line (`engine.speak()`), duration measured and compared to the script's `speech_s`. A line > 1.15× its slot → send back to script.
3. **Keyframes** for H3 shots are made in namo-studio (`keyframes-r2.yml`, prompts from namo-studio `manufacture/SHOW_BIBLE.json` + `CAST_WEIGHTAGE.json`), not here.

### Step 3: GPU Stems (paid) — namo-studio only

Never through `namo/engine.py`. H3 shots are rendered by namo-studio `manufacture/namo_pod_run.py plans/<ep>.json` after `dryrun.yml` (CPU ComfyUI) has validated every graph, into namo-studio `out/<ep>/shots/`; R2 `render/<ep>/shots/` is where this stage reads them (no uploader exists yet — namo-studio `FACTORY_MANUAL.md`, gaps). Its rules, as written there:

- One pod session per run; global weights volume `namo-weights-global`.
- Budget floor `NAMO_BUDGET_FLOOR` (default $0.25): the run stops and keeps the shots made so far.
- A pod is never released on an error: it is held for the fix and resumed on; the in-pod watchdog releases it after 30 min idle.
- On success the pod is released at once (unless `NAMO_KEEP_POD=1`): `pods_alive_after` must be empty.

### Step 4: Verify Every Stem

Video (H3 shots):

```
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_frames:format=duration -of json <SHOT>.mp4
```

Must be `h264`, `yuv420p`, `768x1344`, `24/1`, frames on the 17k+5 grid as the meta says, duration within 0.2 s of spec. Black check:

```
ffmpeg -v error -i <SHOT>.mp4 -vf signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=- -f null -
```

`max(YAVG) <= 17` is a flat-black shot (int8 video VAE renders black — fp16 VAE only). Music: 48 kHz (`ffprobe` `sample_rate`), `volumedetect` `max_volume <= -6.0 dB`, not silent. Then `sha256sum -c SHA256SUMS` inside `render/<ep>/` — every line `OK`.

### Step 5: Submit

Validate the manifest against the schema. Self-check:

- [ ] Every scene-plan shot has its stem, and every stem passed Step 4
- [ ] `sha_verified: true`
- [ ] `pods_alive_after == []`
- [ ] `total_cost_usd` ≤ budget
- [ ] mg renders passed `verify_video`, not merely "file exists"

## Refuse / Fail When

- Any stem fails acceptance: do not assemble. Re-render that shot (same seed and graph first; H3 shots in namo-studio); do not hand a failed stem to edit.
- A GPU run returns mixed, narrated, graded, texted or concatenated output: that is a defect, not a usable asset.
- The estimate exceeds budget.
- An H3 shot is required and not in R2 `render/<ep>/shots/`: the stage fails naming the shot; no substitution with another look, and no GPU rental from the engine.

## Common Pitfalls

- **Trusting the spec instead of ffprobe.** The manifest records what was measured.
- **Renting a GPU from the engine.** H3 shots are namo-studio's; the engine has no GPU runtime.
- **Grading or mixing on the GPU "to save a step".** CPU does all of it.
