# Edit Director — NAMO Customer Pipeline

## When to Use

You cut the client film (`pipeline_defs/namo-customer.yaml`, stage `edit`, `checkpoint_required: true`, `human_approval_default: true`) from the approved `scene_plan` and the licence-cleared `asset_manifest`. The client approves the edit before anything is mastered, so you deliver an `edit_decisions` artifact **and** a watchable proxy preview of it.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/edit_decisions.schema.json` | Artifact validation |
| Prior artifacts | `scene_plan` (approved stills, timings, transitions), `asset_manifest`, `script` (`metadata.customer.cutdowns`), `brief` (`deliverables`, `aspect_ratios`) | Timeline and variants |
| Runtime | `proposal_packet.production_plan.render_runtime` (`remotion` / `hyperframes` / `ffmpeg`) | Must match the approved runtime |
| Brand | `brand.json` + yaml `brand:` | Logo, fonts, colours, safe area |
| Tool | `video_compose` (`render` at proxy size) | Client preview |

## Output Artifact: `edit_decisions`

| Field | Content |
|-------|---------|
| `cuts[]` | Master timeline: one primary cut per scene, in storyboard order, `reason` = scene id |
| `overlays[]` | Logo, text cards, lower thirds: `{asset_id, start_seconds, end_seconds, position, animation, opacity}` |
| `audio` | Narration segments at measured times; music bed with ducking; sfx |
| `subtitles` | `enabled: true`, brand body font, brand colours, `position` per ratio |
| `render_runtime` | The approved runtime — a different one is a runtime swap and needs a logged, client-approved decision |
| `metadata` | `loudnorm_target: -16`, `customer: {variants: [{deliverable_id, ratio, seconds, section_ids, reframe: [{cut_id, crop: [x, y, w, h]}], subtitle_position, logo_box}], preview_path}` |

## Process

### Step 1: Master Timeline

Lay each scene's asset at the storyboard timings; trim to the beat. Narration segments at their measured starts; no line crosses its scene's cut. Transitions from the scene plan; the brand book's motion rules win over the playbook's.

### Step 2: Brand Layer

- Logo overlay where the concept puts it, inside `logo_safe_area_percent` (8 %) of every edge in **every** ratio, at or above `brand.logo.min_width_px`.
- Text in brand fonts and colours; every text element's contrast already measured on the stills — re-measure if its background changed.
- No banned element in any overlay, caption or b-roll.

### Step 3: Variants

For each deliverable in `brief.metadata.customer.deliverables` that is a video (`master`, `social_cut`):

- Ratio: a reframe per cut (`crop` box) that keeps the subject, text and logo inside the frame and the safe area. Never letterbox a social cut unless the brief asks.
- Length: a cut-down uses the script's `cutdowns` section list only — no new copy, no new shots.

### Step 4: Preview and Checkpoint

Render a proxy of the master (and each distinct ratio) with `video_compose` `render`, low resolution, CPU only, no paid calls. Write the checkpoint `awaiting_human` with the preview paths. Client notes are revisions; the third round is a change order.

### Step 5: Validate

- [ ] Every scene has a cut; master timeline has no gaps or overlaps (a gap is a black frame)
- [ ] Every `source` / `asset_id` exists in the manifest
- [ ] Every variant's crop keeps logo and text inside the safe area (check on a frame of each cut)
- [ ] `render_runtime` equals the approved runtime
- [ ] Client approved the preview
- [ ] Schema-valid

## Refuse When

- An asset in the cut has no cleared licence in the manifest.
- A ratio cannot hold the logo and the text inside the safe area without dropping something the brief requires: report it, with the frame.

## Common Pitfalls

- **Approving an EDL.** Clients approve what they can watch; send the proxy.
- **One reframe for all cuts.** Each shot's subject sits differently; crop per cut.
- **Cut-downs that need new lines.** Those are new copy and need their own approval.
