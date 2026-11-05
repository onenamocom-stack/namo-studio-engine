# Edit Director — NAMO Webshow Pipeline

## When to Use

You write the edit decision list for one episode (`pipeline_defs/namo-webshow.yaml`, stage `edit`) from the `scene_plan` and the verified `asset_manifest`. The edit is not a creative re-cut: **shot order comes from the authored shot list**, every shot plays for its beat, and transitions are ink blooms or hard cuts — never dissolves.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Artifact validation |
| Prior artifacts | `scene_plan` (order, timing, `transition_in/out`, runtime per shot), `asset_manifest` (verified stems), `script` (lines, `metadata.namo.beats`) | Timeline |
| Episode | `music` cues (`theme`, `from`/`to` shot ids, `gen`) and `sfx` cues (`shot`, `t`, `name`, `gain_db`) of the episode plan | Audio layers |
| Style | `lemo/styles/ink-wash/STYLE.md` ("Transitions are ink blooms, pans along the scroll or mist; never a generic dissolve or a wipe"; subtitles in the picture's liubai) | Transition and subtitle grammar |

## Output Artifact: `edit_decisions`

| Field | Content |
|-------|---------|
| `cuts[]` | One `primary` cut per shot, in authored order: `{id: "cut-<SHOT>", source: <asset id>, in_seconds, out_seconds, layer: "primary", transition_in, transition_out, reason: "<SHOT> beat"}` |
| `transitions[]` | `{type: "ink_bloom"|"cut", at_seconds, duration_seconds}` |
| `audio.narration.segments[]` | `{asset_id, start_seconds, end_seconds}` — one per spoken line |
| `audio.music` | Bed asset, `volume`, fades; ducking under every voice line |
| `audio.sfx[]` | `{asset_id, start_seconds, volume}` from the episode's sfx cues (`gain_db` → linear) |
| `subtitles` | `enabled: true`, `font: "NotoSerifDevanagari"`, `font_size: 52` (1920-wide render), `source`: the generated `.srt`, `position` per runtime (see Step 3) |
| `render_runtime` | `ffmpeg` (CPU compose) |
| `metadata` | `loudnorm_target: -16` (the `audio_mixer` convention), `true_peak_max_dbtp: -1.5`, `namo: {shot_order: [ids], target_seconds, subtitle_cues: [{id, start, end, text, lang, style: "hi"|"sa"}]}` |

## Process

### Step 1: Lay the Shots

Walk `scene_plan.scenes` in order. For each shot take its verified asset (`asset_manifest.assets[].scene_id`) and place it at the scene's `start_seconds`–`end_seconds`. Trim a clip to its beat; never stretch a clip or change its speed to fill a beat — a clip shorter than its beat is an asset failure (send back), not an edit decision.

Check: cut ids in the same order as `metadata.namo.shot_order`, which equals the authored list; no gaps, no overlaps; last `out_seconds` = target length.

### Step 2: Transitions

- Inside the ink-wash (`mg`) film, transitions are the lemo compositor's ink blooms; they are already in the rendered film — record them in `transitions[]` with `type: "ink_bloom"`.
- Between separately rendered shots (H3 shots made by namo-studio, or an H3 shot next to the mg film), use `cut`. The episode's authored `cut` field marks where a hard cut is required, and compose QA checks for it (`qa_video.py --expect-cuts`).
- `dissolve`, `fade`, `wipe`, `xfade` of any kind: forbidden.

### Step 3: Subtitles

One cue per sentence, its times snapped to the voice pauses:

- Narrator lines (`hook`, `scene`, `explain`): Hindi, ≤ 2 lines × 42 characters.
- Sanskrit lines: their own Devanagari, one small line ≤ 60 characters; the meaning follows in the narrator's voice, not as a translation subtitle.
- English goes only to `final.en.srt`, never burned.
- Placement: inside the shot's liubai (empty paper) for ink-wash shots; inside the safe subtitle box for vertical (768x1344) H3 shots.

### Step 4: Audio

- Narration segments at each line's measured start (`start + air`), ending before the beat ends.
- Music: cues are contiguous (`from` = previous `to`); a cue ending before the next starts, or a `silence` beat, is a hard drop, and no voice may start within 0.5 s after one. Duck the bed under every voice line.
- SFX at their shot-relative `t` converted to film time.

### Step 5: Validate

- [ ] Cut order = authored shot order; every shot exactly once
- [ ] Timeline covers 0 → target with no gap (a gap is a black frame)
- [ ] Every `source` and `asset_id` exists in the manifest
- [ ] No dissolve-family transition
- [ ] Every voice line sits inside its own shot's cut; Sanskrit line under its speaker's shot, explain line under the next shot
- [ ] Every subtitle cue fits its line limits
- [ ] Schema-valid

## Refuse When

- A shot has no verified asset, or its clip is shorter than its beat: send back to assets.
- Measured narration does not fit its shot: send back to script.
- The order in the scene plan differs from the authored list.

## Common Pitfalls

- **Reaching for a dissolve** because two H3 shots do not match. The show cuts; a mismatched shot is re-rendered (in namo-studio).
- **Burning English.** The film is Hindi; English is a sidecar `.srt`.
- **Music under a hard drop.** A voice starting within 0.5 s of a drop lands on silence the score just created.
