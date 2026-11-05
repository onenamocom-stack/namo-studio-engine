# Asset Director — NAMO Webshow Pipeline

## When to Use

You make every stem the episode needs (`pipeline_defs/namo-webshow.yaml`, stage `assets`) from the approved `scene_plan` and `script`, and prove each one is right by measurement. CPU work (ink-wash renders, voice) runs here on the runner; GPU work (H3 clips, music stems) is outsourced and comes back as raw, separated, named stems. **GPU returns stems; it never mixes, narrates, grades or concatenates** (`GPU_CONTRACT.principle`). This is the only stage that spends money.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json` | Artifact validation |
| Prior artifacts | `scene_plan` (`metadata.namo.shots[]`: runtime per shot), `script` (lines, measured timings) | What to make |
| Engine | `python namo/engine.py render <job.json>` — the only door to a runtime (SPEC R2); `mg` returns a verified film, `h3` returns stems (`namo/namo_gpu.py`) | Rendering |
| Contracts | `GPU_CONTRACT.json` (`gpu_outputs`, `format_rules`, `acceptance`), `PROVISIONING_RULES.json` (`hard_rules`, `cost_ceilings`, `boot_timeout_by_image`, `forbidden`) | Stem spec, GPU spend |
| Tools | `tts_selector`, `image_selector`, `video_selector`, `music_gen` (yaml `tools_available`) | Keyframes, music when not on the GPU session |
| Voice | piper `hi_IN-pratham-medium` (`.voices/`) | Narration stems |

## Output Artifact: `asset_manifest`

One `assets[]` entry per file. Closed schema: per-file checks go in `metadata.namo`.

| Field | Content |
|-------|---------|
| `id` | `<SHOT>_video`, `<SHOT>_vo`, `<THEME>_s<SEED>`, … |
| `type` | `video` (h3 clip), `animation` (mg film/shot), `narration`, `music`, `sfx`, `image` (keyframe) |
| `path` | GPU: `render/<ep>/shots/<SHOT>.mp4`, `render/<ep>/music/<THEME>_s<SEED>.wav`; mg: the engine's output film |
| `source_tool` | `engine.mg`, `engine.h3`, `piper`, `music_gen`, `image_selector` |
| `scene_id` | Shot id |
| `model`, `seed`, `provider` | From the stem's `<SHOT>.json` meta (`graph`, `seed`, `gpu`) |
| `cost_usd` | Measured spend for that file (0 for CPU) |
| `duration_seconds`, `resolution`, `format` | Measured with ffprobe, not copied from the spec |
| `license` | H3: "MiniMax H3 output — commercial use must credit 'MiniMax H3' and disclose AI-generated content"; piper voice: the model card's licence; music: its model/source licence |
| `total_cost_usd` | Sum |
| `metadata.namo` | `{sha256sums: path, sha_verified: bool, checks: [{id, codec, pix_fmt, width, height, fps, frames, seconds, spec_seconds, yavg_max, ok}], music_checks: [{id, sample_rate, max_volume_db, mean_volume_db, ok}], pods_created: [ids], pods_alive_after: [], spend_usd}` |

## Process

### Step 1: Inventory and Estimate

List every stem the scene plan needs, grouped by runtime. Cost = Σ(h3 shot seconds) × `0.00039` (`H3Runtime.cost_per_sec_usd`) + boot/pod overhead at the chosen GPU's `price_hr` from `PROVISIONING_RULES.candidate_order`. If the estimate exceeds the showrunner's remaining budget, `cost_ceilings.per_episode_usd`, or the account balance, stop before renting and report the numbers. `session_policy` plans ≥ 8 episodes per pod run; a single-episode rent is a showrunner decision, logged.

### Step 2: CPU Stems First (free)

1. **Ink-wash (`mg`)**: write the job (`namo.job/1`: `kind: webshow`, `runtime: mg`, `scene`, `seconds`, `fps: 24`, `ratio`, `style: namo-vedic-ink`, `voice`) and run `python namo/engine.py render job.json`. Only `PASS` (from `verify_video`: size, duration within 2 %, zero blank frames, audio not silent) counts.
2. **Narration**: one piper WAV per narrator line (`engine.speak()`), duration measured and compared to the script's `speech_s`. A line > 1.15× its slot → send back to script.
3. **Keyframes** for h3 shots (`image_selector`): prompt = `SHOW_BIBLE` + character identity + framing (`casting_rule`: no character from its own prompt alone), plus `negative_prompt`. Every prompt names fire, props, ground.

### Step 3: GPU Stems (paid) via the `h3` Runtime

Only through `python namo/engine.py render` with `runtime: h3` (it dispatches `namo/namo_gpu.py`). Provisioning rules as written:

- No pod without a named GPU type, a named datacenter and a precomputed max cost (R1).
- A pod that has not reported uptime within `boot_timeout_by_image` is deleted at once — a pod is born only when it will boot.
- Never a GPU from `forbidden.gpus_documented` for a render (24–48 GB cannot hold the 52.3 GB weights).
- A pod that booted and then hits an error is held and the fix resumes on it; it is released after 30 continuous minutes with no render and no log change.
- When this stage completes, list the provider's pods (`GET https://rest.runpod.io/v1/pods`, key from env `RUNPOD_KEY`, never printed): `pods_alive_after` must be empty.

### Step 4: Verify Every Stem

Video (`GPU_CONTRACT.acceptance.shot`):

```
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_frames:format=duration -of json <SHOT>.mp4
```

Must be `h264`, `yuv420p`, `480x864`, `24/1`, frames as the meta says, duration within 0.2 s of spec. Black check:

```
ffmpeg -v error -i <SHOT>.mp4 -vf signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=- -f null -
```

`max(YAVG) <= 17` is a flat-black shot (int8 video VAE renders black — fp16 VAE only). Music (`acceptance.music`): 48 kHz (`ffprobe` `sample_rate`), `volumedetect` `max_volume <= -6.0 dB`, not silent. Then `sha256sum -c SHA256SUMS` inside `render/<ep>/` — every line `OK`.

### Step 5: Submit

Validate the manifest against the schema. Self-check:

- [ ] Every scene-plan shot has its stem, and every stem passed Step 4
- [ ] `sha_verified: true`
- [ ] `pods_alive_after == []`
- [ ] `total_cost_usd` ≤ budget
- [ ] mg renders passed `verify_video`, not merely "file exists"

## Refuse / Fail When

- Any stem fails acceptance: `GPU_CONTRACT.acceptance.total` — "CPU refuses to assemble if any shot fails acceptance". Re-render that shot (same seed and graph first); do not hand a failed stem to edit.
- A GPU run returns mixed, narrated, graded, texted or concatenated output: that is a contract defect (`format_rules.no_gpu_mixing`), not a usable asset.
- The estimate exceeds budget or a provisioning ceiling.
- `RUNPOD_KEY` is unset or the provider is unreachable when an `h3` shot is required: the stage fails naming the shot; no substitution with another look.

## Common Pitfalls

- **Trusting the spec instead of ffprobe.** The manifest records what was measured.
- **Deleting a booted pod on the first error.** Fix and resume on the same pod; the weights download is the expensive part.
- **Grading or mixing on the GPU "to save a step".** CPU does all of it.
