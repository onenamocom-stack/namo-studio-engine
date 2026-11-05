# NAMO explainer style (rendiv) — the Codacus bar

Sources, measured 2026-11-06 with ffmpeg frame grabs + pixel sampling (720p downloads):
- R1 "I Built a Free AI Video Editor That Replaced Premiere Pro" — youtube.com/watch?v=DxznNEC4GXw (made with rendiv)
- R2 "1M Context in 500MB?! DeepSeek V4 + TurboQuant Explained" — youtube.com/watch?v=3mX_dc9ZNRA
- R3 "Your GPU Is Nerfed for AI" — youtube.com/watch?v=-2oOpjtKPN4 (isometric blueprint 3D; out of scope on CPU, see bottom)
- rendiv README/API — github.com/thecodacus/rendiv, @rendiv/* 0.2.6 on npm

## Frame
- Background: radial gradient, edge `#07080F` → centre `#111434` (R1 sampled corner (7,8,15), centre (17,21,52)). Never flat black, never a hard black frame between beats.
- Ambient: 8–14 hollow squares (1 px stroke, 6–12 px, 10–30 % opacity) drifting slowly; one faint horizontal light streak (R2). Background keeps moving while content holds.
- Fill: content block spans 60–85 % of frame width (16:9) / 86–90 % (9:16); centred. Landscape layout and type run at 1.35× the 9:16 unit (1 u = 1.35 % of the short side), so nothing sits small in a big empty frame.

## Colour (sampled)
- Text `#F5F7FF`; secondary `#8A90B8`; dim `#4A5080`.
- Accent cyan `#00B8F7` (R1 (0,184,247)) — the one highlighted keyword per headline, lines, carets.
- Danger coral `#FF543F` (R1 (255,84,63)) — contrast/wrong/bias words, stamps.
- Amber `#FBBF24` (R2 overline "◆ THE STORY" peak (227,193,110)) — overlines, numbers of note.
- Teal `#14B8A6` (R1 check circle peak (24,168,149)) — ticks, "correct".
- Card: fill `#101433`, 1 px border `#1C2150`, radius 1.4 % of short side, soft shadow; active card gets a cyan border + 24 px glow.

## Type
- Units: 16:9 → u = 1.35 % of short side (14.6 px); 9:16 → layout u = 1 % (10.8 px), type tu = 1.3 % (14 px).
- Title: Inter 800 / Noto Sans Devanagari 700, 9.5 u (16:9) / 7 tu (9:16), leading 1.25, keyword in accent. Kinetic lines 7.2 u / 5.8 tu.
- Shloka: Noto Serif Devanagari 600, 6.6 u / 5.6 tu.
- Overline: JetBrains Mono 600, Latin 1.7 u UPPERCASE tracking 0.32 em; Devanagari 2.2 u (16:9) / 2.8 tu (9:16), amber, prefixed `◆` (R2).
- Numbers: JetBrains Mono 800 with same-colour glow (`text-shadow 0 0 24px`), 18–24 % of short side (R2 "$0.60", R3 "27.25").
- Caption (English): Inter 500, 2.2 % of short side, `#8A90B8`, bottom 7 % safe area, pill background `#0B0E22cc`.
- Fonts are bundled (`@fontsource/*`, OFL) — no network at render time.

## Motion grammar (frames below are design frames: 30 fps on a 6 s design clock)
- Every beat maps its own length onto the 180-frame design clock, so reveals land at the same fraction of a short or a long beat (a 1.3 s beat still shows its last reveal; a 9 s beat paces out).
- Enter = opacity 0→1 + rise 1.6 % of short side + blur 6 px→0 over 14 f (0.47 s), ease `bezier(0.16,1,0.3,1)` (R1 strip: line goes faint→solid in ~3 frames at 6 fps ≈ 0.5 s).
- Stagger 10 f (0.33 s) between sibling elements (R2 arXiv card builds element by element).
- Cards / nodes / stamps: spring damping 14, stiffness 140, mass 1 (scale 0.86→1 or 1.6→1 for stamps, rotate −8°).
- Typewriter: 22 chars/s with a 2 px cyan caret, blink period 16 f (R2 "The lon|").
- Accent rule above a headline grows from centre 0→12 % of width over 18 f (R1, R2).
- Diagrams: connectors draw with stroke-dash reveal over 16 f, nodes light in sequence 12 f apart (R1 pentagon loop).
- Counters tick to their value over 30 f, ease-out (R1 "$0.06").
- Camera: every beat pushes in 1.00→1.035 over its length (no static frames).
- Beat change: content exits in 8 f (opacity + 1 % rise up); background never cuts (R1/R2 cut to empty bg, then rebuild).
- Hold: after the last element lands, hold ≥ 1.5 s before exit — and the hold keeps moving: content floats ±0.35 u on a 5 s sine; emphasised words breathe their glow (2.2 s) under a drawn underline; cards carry a sheen sweep (3.4 s) and lit cards breathe; connectors carry a travelling light packet (1.4–1.8 s); the stamp sways ±1.5°; big numbers emit a ripple ring (2.2 s); the timeline runs a light pulse; the recap walks a focus band down its items (1.6 s each).
- Narration leads the cut: a beat is at least as long as its spoken line + 0.4 s (`engine.py fitbeats`).

## Beat types (data-driven, `beats/*.json`)
`title`, `kinetic` (shloka / quote, word-by-word, emphasis colours), `flow` (A→B→C with labelled arrows),
`map` (relationship tree), `compare` (two columns + stamp), `number` (big counter + label), `timeline`, `recap` (checklist).

## Known gap vs the bar
- No isometric/3D blueprint hardware (R3) and no face-cam inserts; CPU swiftshader would make WebGL slow.
- No sound design (whooshes/ticks) — Codacus uses subtle SFX on every reveal.
- Reveals are paced by beat length, not synced to the spoken word.
