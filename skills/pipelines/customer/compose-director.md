# Compose Director — NAMO Customer Pipeline

## When to Use

You master the client-approved edit (`pipeline_defs/namo-customer.yaml`, stage `compose`) in **every aspect ratio and length the brief asked for**, then prove each output by measurement: no black frames, brand colours measured on the output frames (not assumed from the edit), loudness and length on spec. Produces `render_report` and `final_review`.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schemas | `render_report.schema.json`, `final_review.schema.json` | Validation |
| Prior artifacts | `edit_decisions` (master + `metadata.customer.variants`), `asset_manifest`, `brief` (`deliverables`, `aspect_ratios`), `proposal_packet` (approved `render_runtime`) | What to render |
| Tools | `video_compose` (`render`, pass `proposal_packet` so runtime-swap detection runs), `audio_mixer` — yaml `required_tools` | Render, mix |
| Engine | `namo/engine.py verify_video(path, seconds)` (SPEC §4) | Blank-frame and duration acceptance |
| Measurement | `brand_share()` / `contrast()` from `storyboard-director` Step 3 | Brand colours, text contrast |

## Process

### Step 1: Render Every Variant

For the master and each `variants[]` entry: mix with `audio_mixer` (`loudnorm_target: -16`, true peak ≤ −1.5 dBTP — the NAMO delivery standard of `GPU_CONTRACT.format_rules.audio_out`, unless the brief names a platform spec), then `video_compose` `render` in the approved runtime at full resolution. Delete the target path first (SPEC O3). One output per deliverable id.

### Step 2: Measure Each Output

| Check | How | Pass |
|-------|-----|------|
| Probe | `ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration,size -of json <out>` | ratio = the variant's ratio; codec/container as the deliverable asks |
| Duration + blank frames | `verify_video(out, seconds)` | duration within `max(0.5 s, 2 %)`; 0 blank frames |
| Black frames | `ffmpeg -v error -i <out> -vf blackdetect=d=0.04:pix_th=0.10 -f null -` | no `black_start` lines |
| Loudness | `ffmpeg -nostats -i <out> -af ebur128=peak=true -f null -` | −16 LUFS ± 1, true peak ≤ −1.5 dBTP |
| Brand colours | extract one frame per scene at its key-frame time (`ffmpeg -ss <t> -i <out> -frames:v 1 f_<scene>.png`); `brand_share(f, expected_hexes, tol)` | every declared brand colour ≥ 1 % of the frame, as on the approved still |
| Text contrast | same frames; `contrast(fg_hex, bg_rgb)` for every text element | ≥ `colour_contrast_min` (4.5) |
| Logo | frame inspection against the variant's `logo_box` | inside the 8 % safe area, never cropped |
| Captions | a frame at every caption's midpoint | present, inside the frame, brand font |
| Banned elements | look at every extracted frame | none |

### Step 3: `render_report`

`outputs[]` — one per deliverable: `{path, format, codec, audio_codec, resolution, fps, duration_seconds, file_size_bytes, platform_target}` from the probe. `verification_notes`: the commands and numbers above, per output.

### Step 4: `final_review`

- `checks.technical_probe` (per master; variants listed in `issues` when they fail), `visual_spotcheck` (`frames_sampled` ≥ 4 per output, `black_frames_detected`, `unreadable_text`), `audio_spotcheck`, `subtitle_check`.
- `checks.promise_preservation`: `render_runtime_used` = what ran; `runtime_swap_detected` must be `false` unless a client-approved decision allows it; `delivery_promise_honored`.
- `metadata.customer.outputs[]`: `{deliverable_id, ratio, lufs, true_peak, blank_frames, brand_share: {hex: share}, min_contrast, logo_ok, ok}`.
- `status: pass` only when every deliverable passed every row. Otherwise `revise` with `recommended_action` (`re_render`, `revise_edit`, `revise_assets`).

## Refuse When

- A requested ratio or length has no variant in the edit: send back to edit; never skip a deliverable.
- A measurement cannot run (no ffmpeg, unreadable output): SPEC O2 — rejection, not a pass.
- The runtime that would run differs from the approved one without a logged client decision.

## Common Pitfalls

- **Measuring the master only.** A 9:16 variant can crop the logo or lose a brand colour the 16:9 had.
- **Trusting the EDL's hex values.** Colour management and encoding shift colours; measure the encoded frames.
- **Normalising stems instead of the final mix.**
