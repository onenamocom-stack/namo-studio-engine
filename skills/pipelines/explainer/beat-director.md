# Beat Director — NAMO Explainer Pipeline

## When to Use

You are the Beat Director for a NAMO explainer (`pipeline_defs/namo-explainer.yaml`, stage `beat_grid`). You have an approved `script` artifact written in chapters. Your job is to turn it into a **beat grid**: one timed list of beats that says, for every second of the film, what is spoken, what the caption bar reads, and what kind of visual carries the beat.

The beat grid is the single source of truth for timing. The scene planner, the asset director, the voice stage and the renderer all read it; none of them re-time anything.

The grid is **runtime-neutral**. It names *what* each beat shows (a visual kind and its content), never *how* to draw it: no coordinates, no colours, no fonts, no engine names. Whichever runtime the scene director picks for a beat implements that visual kind; if it cannot, it refuses the beat by name rather than drawing something else.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Prior artifact | `script` | Chapters, sections, narration text, enhancement cues, delivery cues |
| Pipeline | `pipeline_defs/namo-explainer.yaml` → `structure`, `emotion.pacing` | Cold open, chapter card length, recap points, caption bar, scene hold range |
| Router plan | `namo/agent.py plan()` | `seconds`, `ratio`, `style`, `emotion`, `voice` the film must honour |
| Voice | The Piper voice in the plan (`hi_IN-pratham-medium` for Hindi narration) | Measured line durations |

## Output Artifact: `beat_grid`

A JSON file, schema `namo.beats/1`:

```json
{
 "schema": "namo.beats/1",
 "title": "Gita 1.1, explained",
 "subtitle": "Why a blind king's first question matters",
 "seconds": 75,
 "air": 0.3,
 "timing": "measured",
 "sources": ["Bhagavad Gita 1.1, Sanskrit text"],
 "beats": [
  {"id": "b01", "start": 0, "end": 6, "chapter": 0, "visual": "hook",
   "big": "A blind king.", "small": "One question, before the war.",
   "caption": "A blind king. One question, before the war.",
   "vo": {"text": "एक अंधा राजा। और युद्ध से ठीक पहले, एक सवाल।", "lang": "hi", "measured": 3.4}},
  {"id": "b03", "start": 12, "end": 14.5, "chapter": 1, "visual": "chapter", "n": 1, "name": "The question"}
 ]
}
```

| Field | Rule |
|-------|------|
| `seconds` | Authored length. Equals the last beat's `end` and the plan's `seconds` within 2 % (the `verify_video()` duration gate). |
| `air` | Seconds of silence before and after each line inside its beat (yaml: measured TTS + 0.3 s). |
| `timing` | `measured` once every `vo` line has a real WAV duration in `vo.measured`; `budgeted` only before the voice exists, and then a `timing_note` says so. |
| `beats[].start/end` | Seconds. Contiguous, no gaps, no overlaps, first `start` is 0. |
| `beats[].chapter` | 0 for the cold open, then 1..n. |
| `beats[].visual` | One kind from the vocabulary below, plus that kind's content fields. |
| `beats[].vo` | `{text, lang, measured}`; one narration line per beat. Omit it for silent beats (chapter cards). |
| `beats[].caption` | Short caption for the caption bar (`caption_bar: true`); one idea, at most ~80 characters. |

Narration lines for the voice stage follow from the grid, in output seconds: `{id, t: start + air, end: end - air, text, lang}`. If the plan's `seconds` differs from the grid's `seconds`, the runtime scales every time by `plan.seconds / seconds`, and the VO slots scale with it.

### Visual vocabulary

The contract between the grid and any runtime. A runtime that renders explainers implements every kind it claims; a kind not listed here is added here first, then used.

| `visual` | Content fields | Use for |
|----------|----------------|---------|
| `hook` | `big`, `small` | Cold open: the concrete image, never a definition |
| `title` | — (uses top-level `title`, `subtitle`) | Title card after the cold open |
| `chapter` | `n`, `name` | Chapter card (`chapter_card_seconds`, 2.5 s) |
| `verse` | `lines[]`, `translit[]`, `focus` | Source text on screen, one line highlighted |
| `relation` | `a{head,sub}`, `b{head,sub}`, `label` | Who does what to whom: A → B |
| `split` | `a{head,sub}`, `b{head,sub}` | Two things held side by side |
| `stat` | `big`, `small` | One number that matters |
| `term` | `head`, `sub` | A word and its meaning |
| `recap` | `items[]` (≤ 3) | Re-anchor the viewer (`recap_at`) |
| `perform` | `action`, `props[]` | The character acts the idea out (yaml `performance`) |
| `outro` | `big`, `small` | What comes next |

## Process

### Step 1: Read the Plan and the Structure

From the router plan take `seconds`, `ratio`, `emotion`. From the yaml take `cold_open_seconds`, `chapter_card_seconds`, `recap_at`, `outro_seconds`, `scene_hold`. For a film shorter than the long-form target (20–40 min), shrink proportionally and record it in the decision log: a 75 s explainer gets a ~10 s cold open, three chapters and one closing recap instead of two.

### Step 2: Cut the Script into Beats

- One beat = one narration line + one visual. A line that needs two visuals becomes two beats (e.g. `verse` with `focus` 0, then 1).
- Every chapter boundary gets a silent `chapter` beat.
- Respect `scene_hold`: no beat shorter than 1.5 s or longer than 8 s. Split long lines at a clause.
- Facts go into `sources`. A claim with no source does not get a beat.

### Step 3: Measure, Do Not Guess

Speech is measured, never estimated. Word count / 2.6 wps is not a duration.

1. Synthesize every `vo.text` with the plan's Piper voice and rate.
2. Read each WAV's real length (`ffprobe -v error -show_entries format=duration -of csv=p=0 line.wav`) into `vo.measured`.
3. Beat length = `air + measured + air`, rounded up to 0.1 s, and at least the visual's minimum (chapter 2.5 s, `scene_hold` 1.5 s).
4. Sum the beats. If the total differs from `plan.seconds` by more than 2 %, trim or merge beats; never stretch or speed up speech to fit.
5. Set `timing: "measured"`.

### Step 4: Pick Visual Kinds

- No three consecutive beats with the same `visual` (scene-director rule).
- Hard cut on a claim, a number, a reversal (`hard_cut_on`): give each its own beat.
- Captions translate the narration into one plain idea; they do not repeat the text already on the visual.

### Step 5: Validate

1. `beats[0].start == 0`, each `start` equals the previous `end`, last `end == seconds`.
2. Every `visual` is in the vocabulary and carries its content fields.
3. Every beat with `vo` has `vo.measured` and `air + vo.measured + air <= end - start`.
4. Every caption fits: ~80 characters, one idea.

### Step 6: Submit

Save the grid as the `beat_grid` artifact (`beats.json`), record the measured durations and any shrink decisions in the decision log, and hand it to the scene director, who assigns a runtime per beat.

## Common Pitfalls

- **Guessed timing**: a grid built from word counts drifts by seconds per minute and the film fails the 2 % duration gate. Measure.
- **Drawing instructions in the grid**: positions, colours or engine names tie the grid to one runtime. Name the visual kind and its content only.
- **Beats with gaps**: narration and picture stop agreeing for the length of the gap.
- **Inventing a visual kind**: a runtime must refuse a kind it does not implement; a film that silently drops a beat looks like success.
- **Unsourced claims**: an explainer is a teaching film. Every fact on a card traces to `sources`.
