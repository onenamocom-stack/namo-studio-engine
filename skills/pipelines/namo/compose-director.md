# Compose Director — NAMO Webshow Pipeline

## When to Use

You render the finished episode on CPU (`pipeline_defs/namo-webshow.yaml`, stage `compose`) from `edit_decisions` and the verified `asset_manifest`, then judge it by measurement. You produce `render_report` and `final_review`. The render is **rejected** if any frame is flat black, the loudness is off, the length is wrong, or the subtitles are missing — a film that "looks done" is not evidence.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schemas | `schemas/artifacts/render_report.schema.json`, `final_review.schema.json` | Artifact validation |
| Prior artifacts | `edit_decisions`, `asset_manifest`, `script` (target length, lines) | What to render |
| Tools | `video_compose` (operation `render`/`compose`, `burn_subtitles`), `audio_mixer` (ducking, `loudnorm_target`) — yaml `required_tools` | Render, mix |
| Engine | `namo/engine.py verify_video(path, seconds, voice)` (SPEC §4) | Acceptance |
| Contract | `GPU_CONTRACT.format_rules` (`audio_out`: 48 kHz stereo, −16 LUFS integrated, true peak −1.5 dBTP; `video`: h264, yuv420p, 24 fps) | Output spec |

## Process

### Step 1: Pre-Render Checks

- Every `cuts[].source` and audio `asset_id` resolves to a manifest path that exists and passed asset acceptance.
- `render_runtime == "ffmpeg"`. CPU only: no GPU call, no provider call from this stage.
- Delete any previous output at the target path first (SPEC O3: a stale file never satisfies a run).

### Step 2: Mix

With `audio_mixer`: narration segments at their times, music bed ducked under every voice line, sfx at their gains, `loudnorm_target: -16`. Output 48 kHz stereo.

### Step 3: Render

With `video_compose`: concatenate cuts in order (hard cuts between separately rendered clips; ink blooms are already inside the mg film), mux the mix, encode h264 / yuv420p / 24 fps, AAC 48 kHz stereo. Burn the subtitle cues as Devanagari (`NotoSerifDevanagari`, 52 px on a 1920-wide frame; Sanskrit as one small line) inside the liubai / subtitle box. Write the film to a temporary name and move it into place only when the encode completed — a film is never published half-made.

### Step 4: Measure

| Check | Command | Pass |
|-------|---------|------|
| Container, codec, size, fps | `ffprobe -v error -show_entries stream=codec_name,pix_fmt,width,height,r_frame_rate,sample_rate,channels:format=duration,size -of json final.mp4` | h264, yuv420p, 24 fps, AAC 48 kHz 2 ch |
| Duration | from the probe | within 5 % of target (yaml) **and** within `max(0.5, 2 %)` (SPEC §4 — the stricter one decides) |
| Blank frames | `verify_video(final.mp4, seconds, voice)` — samples 1 fps at 64×36, luma stddev < 1.0 is blank | 0 blank frames |
| Flat black | `ffmpeg -v error -i final.mp4 -vf signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=- -f null -` | no frame with YAVG ≤ 17; per-shot YAVG has variance (a static black hold is a failure even if one frame is lit) |
| Loudness | `ffmpeg -nostats -i final.mp4 -af ebur128=peak=true -f null -` | integrated −16 LUFS ± 1; true peak ≤ −1.5 dBTP |
| Silence | `verify_video` audio report (mean volume above −50 dB) | narration audible |
| Cuts | namo-studio `qa/qa_video.py final.mp4 --lufs -16 --tp -1.5 --expect-cuts <t1,t2,…>` (cut times from `transitions[]` of type `cut`) | exit 0 |
| Subtitles | extract a frame at the midpoint of every cue (`ffmpeg -ss <t> -i final.mp4 -frames:v 1 cue_<id>.png`) and inspect | every cue present, inside the frame, Devanagari renders (no tofu boxes), 52 px |

### Step 5: Write `render_report`

`outputs[]`: `{path, format: "mp4", codec: "h264", audio_codec: "aac", resolution, fps: 24, duration_seconds, file_size_bytes}` — all from the probe. `render_time_seconds`, `warnings[]`, `verification_notes` (the commands above and their numbers).

### Step 6: Write `final_review`

- `checks.technical_probe`: probe values, `valid_container`, `has_audio`.
- `checks.visual_spotcheck`: `frames_sampled` ≥ 4 (opening, each Sanskrit line, last frame), `frame_paths`, `black_frames_detected`, `unreadable_text`.
- `checks.audio_spotcheck`: `narration_present`, `music_present`, `unexpected_silence`, `clipping_detected` (true peak > −1.5), `mix_intelligible`.
- `checks.promise_preservation`: `render_runtime_used: "ffmpeg"`, `runtime_swap_detected: false`, `delivery_promise_honored` = Sanskrit rule visible in the cut (each Sanskrit line on its speaker's shot, explain on the next).
- `checks.subtitle_check`: `subtitles_expected: true`, `subtitles_present`, `coverage_ratio` (= cued voice seconds / total voice seconds), `timing_drift_detected`.
- `status`: `pass` only if every row of Step 4 passed. `revise` with `recommended_action` `re_render` (encode/mix fault), `revise_edit` (timeline), `revise_assets` (a black or wrong stem). `fail` + `block` when a limit is reached.
- `metadata.namo`: `{integrated_lufs, true_peak_dbtp, blank_frames, yavg_min, duration_delta_pct}`.

## Refuse When

- Any input stem is missing or failed acceptance (no partial film).
- A measurement could not run (ffmpeg/ffprobe absent, file unreadable): SPEC O2 — that is a rejection, never a pass.

## Common Pitfalls

- **Normalising on the stems instead of the final mix.** Loudness is measured on `final.mp4`.
- **Missing the black hold.** One black clip in the middle passes a "first/last frame" glance; per-frame YAVG catches it.
- **Burning subtitles with a font that lacks Devanagari conjuncts.** Inspect the frames; boxes or broken ligatures are a fail.
