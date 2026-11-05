# Concept Director — NAMO Customer Pipeline

## When to Use

You turn the approved `brief` into **three genuinely different concepts**, each with its cost and its time, and take them to the client to pick one (`pipeline_defs/namo-customer.yaml`, stage `concept`, `checkpoint_required: true`). Produces `proposal_packet` and `decision_log`.

This is the last free exit: nothing is generated for money before the client picks.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schemas | `proposal_packet.schema.json`, `decision_log.schema.json` | Validation |
| Prior artifact | `brief` (incl. `metadata.customer`) | Constraints |
| Brand | `clients/<client>/brand.json` | Look and voice authority |
| Runtimes | `video_compose` `get_info()["render_engines"]` (remotion / hyperframes / ffmpeg); `python namo/engine.py probe` (mg, h3) | What can actually render now |
| Costs | `tools/cost_tracker.py`, each tool's `estimate_cost` via the registry | Per-concept cost |
| Reference | `skills/pipelines/explainer/proposal-director.md` (runtime presentation rule), `skills/meta/animation-runtime-selector.md` | Runtime choice |

## Output Artifact: `proposal_packet`

| Field | Content |
|-------|---------|
| `concept_options[3]` | `{id, title, hook, narrative_structure, visual_approach, suggested_playbook, target_audience, target_platform, target_duration_seconds, key_points (≥ 2), core_message, cta, tone, grounded_in, why_this_works}` |
| `selected_concept` | `{concept_id, rationale, modifications}` — your recommendation until the client picks, then the client's pick |
| `production_plan` | `{pipeline: "namo-customer", stages, render_runtime, renderer_family, playbook, voice_selection, music_source, delivery_promise, quality_tradeoffs}` for the selected concept |
| `cost_estimate` | `{total_estimated_usd, line_items, budget_cap_usd, budget_verdict, savings_options}` for the selected concept |
| `approval` | `{status: "pending"}` → client sets `approved` / `approved_with_changes` / `rejected`; `approved_budget_usd` |
| `metadata.customer.per_concept` | `[{concept_id, estimated_usd, line_items: [{item, tool, usd}], estimated_hours, render_runtime, fits_deadline: bool, fits_budget: bool}]` — the yaml requires cost **and** time per concept |

## Process

### Step 1: Constraints First

From the brief: duration, ratios, deadline, budget ceiling, must-says, must-avoids, brand. Remaining time = deadline − now − client checkpoint time already used. A concept that cannot fit both is not offered.

### Step 2: Three Different Concepts

Different means: a different `narrative_structure` **and** a different `visual_approach` for each of the three, and at least two different production paths (e.g. kinetic typography on HyperFrames; product footage + motion graphics on Remotion; generated-image story). Three tones of the same idea is one concept.

Every concept:
- carries every must-say verbatim in its `key_points` or `cta`;
- uses only brand colours and fonts in `visual_approach`;
- has a hook that works in the first 3 seconds, sound off (captions);
- names its `render_runtime`, which must be available now (an unavailable runtime is not offered).

### Step 3: Cost and Time per Concept

Itemise every paid operation per concept (voice, images, video clips, music licence or generation) using each tool's estimate; free CPU work at $0. Time = generation + render + review rounds. Fill `metadata.customer.per_concept`. Mark `fits_budget` / `fits_deadline` honestly; a concept that fails either is dropped and replaced.

### Step 4: Present and Wait

Show the three side by side: title, hook, structure, look, runtime, cost, time. Recommend one, with the reason tied to the brief. Write the checkpoint `awaiting_human` with `approval.status: "pending"`. Do not write the final `render_runtime` until the client approves (proposal-director rule).

### Step 5: Record the Decision

After the client picks, update `selected_concept` and `approval`, rebuild `production_plan` and `cost_estimate` for the pick, and append to `decision_log`:

- `concept_selection`: all three in `options_considered`, the pick in `selected`, the client's reason in `reason`, `user_approved: true`.
- `render_runtime_selection`: runtimes considered, the chosen one, why; unavailable runtimes recorded as rejected.
- `music_source` and `voice_selection` with their licence basis.

### Step 6: Validate

- [ ] 3 `concept_options`, pairwise different in structure and visual approach
- [ ] Each has cost and time in `metadata.customer.per_concept`
- [ ] Every must-say present verbatim in each concept
- [ ] `approval.status` is the client's answer, not yours
- [ ] Both artifacts schema-valid

## Refuse When

- No concept fits the budget and the deadline: report the cheapest/fastest possible and what it would need (more money, more time, fewer deliverables).
- The client asks for a fourth round of concepts beyond `max_revisions_per_stage`: change order (executive producer).

## Common Pitfalls

- **Pretend diversity.** Same structure, three colour schemes.
- **Total-only pricing.** The client compares concepts by line items.
- **Offering a runtime that is not installed.** The pick becomes a promise the compose stage cannot keep.
