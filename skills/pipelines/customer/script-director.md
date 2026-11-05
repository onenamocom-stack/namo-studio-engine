# Script Director — NAMO Customer Pipeline

## When to Use

You write the script of the client's approved concept (`pipeline_defs/namo-customer.yaml`, stage `script`) in the client's brand voice. No filler, no "in today's world", no "let's dive in". Every line earns its second: it carries a key point, a must-say, the hook or the CTA, or it is cut.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/script.schema.json` | Artifact validation |
| Prior artifact | `proposal_packet` (selected concept, `production_plan.voice_selection`), `brief` (must-say, must-avoid, duration, languages) | What to say |
| Brand | `clients/<client>/brand.json` (`voice`, `do_nots`, `banned_elements`) + yaml `brand.banned_elements` | Voice and limits |
| Voice | The approved TTS voice (`tts_selector`, or piper for a local voice) | Measured durations |

## Output Artifact: `script`

| Field | Content |
|-------|---------|
| `title` | From the selected concept |
| `total_duration_seconds` | The master's measured length |
| `voice_performance` | `{performance_intent, pacing_profile, energy_curve}` from the concept's tone |
| `sections[]` | `{id, label (hook / point-n / cta), text, start_seconds, end_seconds, speaker_directions, delivery_cues, pronunciation_guides, source_ref}` |
| `sections[].source_ref` | What earns the line: `must_say:<n>`, `key_point:<n>`, `hook`, `cta` |
| `pronunciation_guides` | Brand, product and person names with their phonetic spelling, confirmed with the client when unsure |
| `metadata.customer` | `{must_say_coverage: [{must_say, section_id}], banned_hits: [], cut_lines: [..], measured: [{section_id, seconds}], languages: [..]}` |

## Process

### Step 1: Skeleton

From the concept: hook (≤ 3 s), the key points in order, the CTA last. Each section gets its `source_ref` before it gets words.

### Step 2: Write in the Brand Voice

- Use `brand.json.voice` literally: if it says "no superlatives", no "best", "ultimate", "revolutionary".
- Must-says are inserted **verbatim**, as a whole line or inside a line, never paraphrased or split.
- No line without a `source_ref`. Cut any sentence that only connects two others.
- Banned list: none of `brand.banned_elements`, yaml `brand.banned_elements`, `brief.metadata.customer.must_avoid`, nor generic filler ("in today's world", "game-changer", "let's dive in", "unlock", "seamless").

### Step 3: Measure

Synthesise every section with the approved voice; read each WAV's real length (`ffprobe -v error -show_entries format=duration -of csv=p=0 line.wav`). Section length = measured speech + ≥ 0.3 s air on each side. Total within 2 % of `target_duration_seconds`; over → cut lines (never a must-say), under → hold on visuals, never pad words.

Social cuts listed in `brief.metadata.customer.deliverables` with a shorter `seconds` get their own cut-down section list in `metadata.customer.cutdowns: [{deliverable_id, section_ids, measured_seconds}]`, built only from master lines (no new copy to approve).

### Step 4: Validate

- [ ] Every must-say appears verbatim in some `sections[].text` (exact substring check) — list in `must_say_coverage`
- [ ] `banned_hits` is empty (case-insensitive substring check against all banned lists)
- [ ] Every section has a `source_ref`
- [ ] Every duration measured; total within 2 %
- [ ] Each cut-down measured within 2 % of its deliverable length
- [ ] Schema-valid

## Refuse When

- The must-says alone, spoken by the approved voice, do not fit the length: report the measured minimum length to the executive producer.
- A must-say contains a banned word (resolved at brief; if it reappears, stop).

## Common Pitfalls

- **Paraphrasing legal copy** to make it "flow".
- **Word-count timing.** Voices differ in pace; measure the voice the client approved.
- **New lines in cut-downs.** A cut-down that adds copy needs its own client approval; build it from master lines.
