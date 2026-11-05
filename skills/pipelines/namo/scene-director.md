# Scene Director — NAMO Webshow Pipeline

## When to Use

You turn the episode's **authored** shot list into a `scene_plan` (`pipeline_defs/namo-webshow.yaml`, stage `scene_plan`). The author has already decided the shots. You may not add, remove, merge, split or reorder a shot. Your job is to bind each shot to its script beat, to a runtime that can actually make it, and to one of the show's two looks — and to refuse a shot that no available runtime can make.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/scene_plan.schema.json` | Artifact validation |
| Shot list | yaml `contracts.shots` = `show/{ep}/shots.json`; for a v2 episode the authored list is `beats[]` of namo-studio `manufacture/plans/<ep>_episode.json` (written and checked by `namo_write.py check`) | The shots — authority |
| Prior artifact | `script` (`sections[].id` = shot id, timings, `metadata.namo.beats`) | Timing per shot |
| Engine | `python namo/engine.py probe` → `REGISTRY` | Which runtimes exist now |
| Bible | namo-studio `manufacture/SHOW_BIBLE.json` (`per_shot_rule`, `light_logic`, `photography`, `banners`, `negative_prompt`) | Shot validity |
| Playbooks | `namo-vedic-ink` (mg ink-wash, `lemo/styles/ink-wash/STYLE.md`), `namo-vedic-painted` (painted look of H3 shots and plates) | The only two looks |

## Runtimes (yaml `stages[scene_plan].runtimes`)

| Runtime | What | Limit | Look |
|---------|------|-------|------|
| `mg` | ink-wash vector, lemo engine, CPU, ~0.04 s/frame, free | the scene's `scene.json` `seconds_range` for the whole film | `namo-vedic-ink` |
| `h3` | MiniMax H3 image-to-video, GPU — **not an engine runtime**: made only by namo-studio `manufacture/namo_pod_run.py` (768x1344, 24 fps) | an existing namo-studio shot in R2 `render/<ep>/shots/` | `namo-vedic-painted` |
| `plate` | still image + 2.5D camera move, CPU | — | `namo-vedic-painted` |

A runtime may be assigned only if it is in `engine.REGISTRY` after `probe` (SPEC R1/R2). Today `namo/engine.py` registers candidates `mg` and `rd` only (the webshow uses `mg`); `plate` has no runtime class, so a shot can be assigned `plate` only once one is registered. `h3` is never in `REGISTRY`: a shot may be bound to `h3` only when namo-studio has already published it to R2 `render/<ep>/shots/<SHOT>.mp4`; otherwise it is a namo-studio episode (see namo-studio `FACTORY_MANUAL.md`).

## Output Artifact: `scene_plan`

One `scenes[]` entry per authored shot, same order, same ids. Closed schema objects, so the NAMO binding goes in `metadata.namo.shots[]`.

| Field | Content |
|-------|---------|
| `id` | The authored shot id (`A1`, `B2x`, …) |
| `type` | `animation` for `mg`; `generated` for `h3` and `plate` |
| `description` | The authored `who` + `action`, verbatim |
| `start_seconds` / `end_seconds` | From the script section with the same id |
| `script_section_id` | Same id |
| `framing` / `movement` | The authored `camera` (e.g. `"medium wide, slow push in"`) |
| `shot_language.lighting_key` | `low_key` for interiors (one fire or lamp), `natural` for hard-sun exteriors — per `SHOW_BIBLE.light_logic` |
| `shot_language.color_temperature` | `warm` (never cool daylight indoors) |
| `texture_keywords` | The authored `props` + `ground` |
| `transition_in` / `transition_out` | `ink_bloom` or `cut` (from the authored `cut`) — never `dissolve` |
| `required_assets[]` | `{type: "video"|"animation"|"image", description, source: "generate"}` |
| `style_playbook` | `namo-vedic-ink` |
| `metadata.namo.shots[]` | `{id, runtime, style, seconds, runtime_max_s, set, fire, props[], ground, cast[], keyframe, why}` |

## Process

### Step 1: Load the Authored List

Read the shot list. If neither `show/{ep}/shots.json` nor the episode plan exists, refuse — you do not write shots. Record the count `N` and the id order.

### Step 2: Bind to the Script

Every shot id must have exactly one script section with the same id and vice versa. A mismatch is a script or shot-list error; send it back, do not paper over it.

### Step 3: Check Each Shot Against the Bible

`SHOW_BIBLE.per_shot_rule`: every shot names its visible light source (`fire`), the props present, and the ground material. A shot missing any of them is invalid. Banners only as `SHOW_BIBLE.banners` assigns them. Interiors are lit by sacred fire or oil lamp only.

For explain beats (`…x`), confirm the Sanskrit rule at picture level: the speaker of the preceding Sanskrit line is not in the explain shot's `cast`, and its `who` differs.

### Step 4: Assign Runtime and Style

For each shot pick the cheapest runtime in `REGISTRY` that can show what the shot describes:

- Ink-wash vector (`mg`) for the show's spine: verse cues on the paper, the hall drawn in ink, the armies as washes. Free.
- `h3` for shots that need photographic motion of cast (lips moving on a Sanskrit line, a chariot moving) — only an H3 shot namo-studio has already made; the engine never renders one.
- `plate` only when registered.

Write `why` per shot in one line. At least one shot must be `mg` — the ink-wash is the show's spine.

### Step 5: Validate

- [ ] `len(scenes) == N`, ids and order identical to the authored list
- [ ] Every shot has a runtime that is in `REGISTRY` (or `h3` with its namo-studio shot already in R2) and a style from the two playbooks
- [ ] ≥ 1 `mg` shot
- [ ] No shot longer than its runtime's limit
- [ ] Every shot names fire, props, ground
- [ ] Scenes contiguous: each `start_seconds` = previous `end_seconds`
- [ ] Schema-valid

## Refuse When

- A shot cannot be made by any registered runtime within its limit: name the shot, its length, and the runtimes tried. Do not shorten, split or drop it — that is the author's call.
- The authored list and the script disagree.
- A shot breaks `per_shot_rule` or the bible's banner/forbidden rules.

## Common Pitfalls

- **"Improving" the shot list.** One added cutaway breaks the author's timing and the Sanskrit rule's beat pairing.
- **Assigning `h3` to save effort.** It costs GPU pod hours in namo-studio and still needs compose; ink-wash is free and is the show's look.
- **Assigning a runtime that is not registered.** The film will fail in assets, after money may already be spent.
