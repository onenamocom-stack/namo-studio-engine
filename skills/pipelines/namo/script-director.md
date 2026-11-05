# Script Director — NAMO Webshow Pipeline

## When to Use

You write the spoken script of one NAMO episode (`pipeline_defs/namo-webshow.yaml`, stage `script`) from an approved `research_brief`. You choose which half-lines are spoken, write the Hindi that explains them, and time every line by measuring real speech.

You never write Sanskrit. The Sanskrit of every line is the `metadata.namo.shloka[]` text of the research brief, copied character for character.

## The Sanskrit Rule (owner's rule, every episode, no exceptions)

1. A Sanskrit line is **seen spoken**: its beat shows the speaker on screen saying it (speaker in that beat's `cast`).
2. The **very next** beat is kind `explain`: speaker `narrator`, language `hi`, the meaning retold as natural spoken Hindi storytelling, over a **new** picture of what the words describe (the event, the army, the person spoken of) — never the speaker's face again (the speaker is not in its `cast`).
3. An `explain` beat appears nowhere else.

This is `namo_audio.sanskrit_rule()` in namo-studio; `make_plan` refuses an episode that breaks it. Your script must pass it before you submit.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/script.schema.json` | Artifact validation |
| Prior artifact | `research_brief` (`metadata.namo.shloka`, `.speakers`, `.lemmas`, `.world`) | Text, speakers, words |
| Router plan | `seconds`, `voice` (`hi_IN-pratham-medium`), runtime | Length, voice, format |
| Voice | piper, model `.voices/hi_IN-pratham-medium.onnx` (`namo/engine.py voice_model()`/`speak()`) | Measured durations |
| Format reference | `namo/mg/scenes/<scene>/story.js` (mg) or namo-studio `manufacture/plans/ep01_episode.json` (H3 v2) | Beat shape |

## Two Formats, One Rule

| | `mg` ink-wash film (`namo/mg/scenes/<scene>`) | H3 episode (namo-studio `plans/<ep>_episode.json`) |
|---|---|---|
| Length | plan `seconds` (webshow default 60; the scene accepts its `scene.json` `seconds_range`) | 80–95 s (`namo_write.py RUNTIME`) |
| Sanskrit lines | 5 subtitle cues (yaml: "60 seconds, 5 subtitle cues"), each followed by its explain beat | 4–6 dialogue beats, each followed by its explain beat; 3–5 narrator bridges (`hook`/`scene`); 0–2 `silence` beats; 15–23 beats total |
| Voices | one piper voice speaks Hindi **and** Sanskrit (`engine.build_voice`: "Sanskrit is spoken by the Hindi voice") | narrator = plan voice; each dialogue line in its speaker's own cast voice (`GPU_CONTRACT.cpu_does`: "dialogue (per-character voice)") |
| Speech fit | a line may be sped up ≤ 1.15× (`ATEMPO_MAX`) to fit; past that the render fails | beat = `voice_in` + measured speech + tail on the 24 fps 17k+5 frame grid; ≤ 8 s per beat; silence 2.3 s |

For `mg`, the scene renders its own authored `window.VO` lines; the engine cannot make a scene say a different script. If your script differs from the scene's authored cues, the stage output is a script **plus** the statement that the scene must be re-authored before render — never a script that the renderer will silently ignore (SPEC §6).

## Output Artifact: `script`

One `sections[]` entry per beat, in order. The schema's section object is closed, so NAMO fields map as follows and the full beat record goes into `metadata.namo.beats[]`:

| Schema field | NAMO meaning |
|--------------|--------------|
| `id` | Shot/beat id: `A1` style (letter = scene, digit = shot); an explain beat is its Sanskrit beat's id + `x` (`B2` → `B2x`) |
| `label` | Beat kind: `hook`, `scene`, `dialogue`, `explain`, `silence` |
| `text` | The spoken line: Devanagari Sanskrit (dialogue) or Hindi (narrator) |
| `start_seconds` / `end_seconds` | Beat window; contiguous, first is 0, last equals `total_duration_seconds` |
| `speaker_directions` | `"<speaker> (<lang>)"` plus on-screen note, e.g. `"dhritarashtra (sa), on screen, own voice"` |
| `source_ref` | Verse id + half (`M.6.23.1 a`) for dialogue and explain beats |
| `delivery_cues.pause_before_seconds/after` | The air around the line, ≥ 0.3 s each |
| `voice_performance.pacing_profile` | `contemplative` |

`metadata.namo.beats[]`: `{id, kind, speaker, lang ("sa"|"hi"), verse, padas (["a"]|["c"]), cast[], voice_in, speech_s (measured), air_s, en}` — `en` is the English rendering of narrator lines, for `final.en.srt` only. `metadata.namo.verses{}`: `{verse_id: {hi, en}}` — the meaning of exactly the spoken padas, prefixed with whose words they are **in the text** (`"अर्जुन: …"` even when Sanjaya voices them), ≤ 80 characters, faithful, no added ideas.

## Process

### Step 1: Choose the Lines

From the research brief take the half-lines that carry the episode. One spoken Sanskrit line = one half-line (`a` or `c`), ≤ ~50 Devanagari characters, ≤ 5 s spoken. Speakers come from `metadata.namo.speakers[].voiced_by`.

### Step 2: Build the Arc

Open on a concrete image (`hook`), never a definition. Dhritarashtra's "uvāca" is a **question**: the episode ends on it, unresolved. No moral, no summary, no "and so we learn". The last beat is a cliffhanger hook or the open question itself.

### Step 3: Write the Hindi

- Explain beats: ≤ ~5 s, ~45–60 characters, plain everyday Hindi (no heavy tatsam words); they may name who speaks: `"राजा पूछता है — …"`.
- Narrator bridges tell a common viewer who is who and why it matters.
- One speaker per beat.
- Every Hindi sentence (split at `।` `?` `!`) fits two subtitle lines of 42 characters; a Sanskrit line fits one line of 60 characters (`namo_audio.SUB`). For the 1920-wide ink-wash render also measure the line at 52 px with the scene font: `PIL.ImageFont.truetype("lemo/styles/ink-wash/demo/fonts/NotoSerifDevanagari-VF.ttf", 52).getlength(line)` must fit inside the subtitle box; split at a clause if not.

### Step 4: Measure, Never Estimate

1. Synthesise every line with the voice that will speak it (`python -m piper -m .voices/hi_IN-pratham-medium.onnx -i line.txt -f line.wav`, length scale from the model json, as `engine.speak()` does; H3 dialogue with the speaker's cast voice).
2. Read the real duration from the WAV into `speech_s`.
3. Beat length = air + `speech_s` + air with air ≥ 0.3 s (PRE14), at least `voice_in` where a hard music drop precedes it (no voice within 0.5 s after a drop). H3: round up to the 17k+5 frame grid.
4. Sum. Off target by more than 2 % → cut or merge narrator bridges. Never speed speech beyond 1.15× and never drop a Sanskrit line's explain beat to save time.

### Step 5: Validate

- [ ] Every dialogue `text` equals the research brief's Devanagari for that half-line (normalised compare)
- [ ] Sanskrit rule: run namo-studio `namo_audio.sanskrit_rule(beats)` (or the same three checks by hand) → `[]`
- [ ] Every beat: `air + speech_s + air <= end - start`
- [ ] Subtitle fit (characters and, for mg, 52 px measurement)
- [ ] Ends on the question; no moral line anywhere
- [ ] Schema-valid

Submit with the measured durations; the showrunner sends you back if a later stage measures longer speech than you did.

## Refuse When

- The research brief has no DCS-verified text for a line you need.
- The plan's length cannot hold the required Sanskrit lines with their explain beats at measured speech.
- The voice model is unavailable (`voice_model()` error): no measurement, no script.

## Common Pitfalls

- **Answering the question.** The Gita opens on a blind father's question; the episode does not answer it for him.
- **Explaining over the speaker's face.** The explain beat shows what the words describe, never the speaker again.
- **Word-count timing.** Characters-per-second is only a first draft (namo_write does this, then re-measures); the script ships measured.
