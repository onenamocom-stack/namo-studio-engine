# NAMO Studio Engine — notes for a fresh agent

**Operating manual (setup, runs, gates, costs, gaps, where things live): `onenamocom-stack/namo-studio` →
`FACTORY_MANUAL.md`.** `SPEC.md` is the engine's contract. This file keeps only engine-internal facts.

```
brief text -> namo/agent.py (router, deterministic) -> plan
plan       -> namo/writer.py  (screenwriter)       -> beats: text, cast, picture, MEASURED slot
beats      -> namo/writer.py  gate_beats()          -> 8 binary answers; any NO = no film
plan+beats -> namo/engine.py  (runtime: mg | rd)    -> film
film       -> namo/engine.py  verify_video()        -> paper + ink + audio + speech, or reject
queue      -> namo/factory.py                       -> all of the above, unattended -> status.json
```

## The writer is the layer that was missing

Until 2026-11-06 there was no screenwriter. `agent.py` says so itself: it routes, it does not
think. Every film therefore used a scene someone typed by hand, so line length, beat order and
who is on screen were whatever the author happened to write. The last shipped webshow put 14 s
of speech inside a 60 s render; the other 46 s was nothing, which is what "weak film, long
unnecessary dialogue, music out of sync" means in code.

`namo/writer.py` fixes that by measuring instead of assuming:

- `speak_seconds(text, lang)` counts Devanagari aksharas and converts at 0.191 s/syllable
  (Hindi) or 0.300 s/syllable (Sanskrit shloka). A line is never timed by character count.
- `fitting_length(brief, want)` returns the film the script can honestly carry. Ask for 60 s
  with three verses and it gives **47 s**, not a padded 60 s.
- `to_shots()` gives each beat a slot of at most `MAX_HOLD_RATIO` (1.6x) its own speech, so a
  shot can never hold 12 s over a 4 s line.
- `gate_beats()` answers eight questions YES/NO and refuses on any NO: fits the film, no line
  overruns its shot, every speaking beat has a speaker, no empty beat, every shloka followed by
  its explain (the owner's Sanskrit rule), no repeated picture, no shot drags, film filled to 85 %.

`tests/test_writer.py` pins each of those against the defect it prevents, including the
14 s-in-60 s shape of the last shipped film. It runs in CI (`.github/workflows/namo-tests.yml`).

**Still not built:** the music beat-grid. `to_shots()` produces slots; nothing aligns a cut to
the tanpura bed, so "music out of sync" is only half fixed - the picture now has rhythm, the
bed does not follow it.
GPU (MiniMax H3) episodes are not an engine runtime; namo-studio makes them.

## Runner notes (each cost time once)
- Use the runner's `google-chrome` and export `PLAYWRIGHT_CHROME`; `apt install chromium` pulls snap (+~5 min).
- ffmpeg from `FedericoCarboni/setup-ffmpeg@v3`; `apt-get install ffmpeg` once took 36 min.
- `namo/bootstrap.sh` clones `ftm/` (ft-motion, vendors lemo + the p5 animation kit) and `lemo/`; engines are cached on
  its hash. `rd` uses playwright's own chromium (`npx playwright install chromium`).
- One render worker per core: 4 browsers on a 2-core runner thrashed.

## Why the mastering is what it is
- Gain is set on the voice alone (speech −16 LUFS), not on the whole film: in `gita-ep01` (~13 % speech) the bed in the
  pauses passes the R128 gate and chasing −16 integrated cost ~8 dB of limiting on the voice.
- AAC overshoots the PCM peak (~+1.2 dB): limiter at −2.5 dBTP, the encoded film is measured and re-limited once.
- A short room reverb lowered the 2–8 Hz envelope modulation (intelligibility proxy) 0.559 → 0.551, so there is none.
- `namo/audio/tanpura.flac`: seamless 9.85 s loop from our own ACE-Step v1 run (Apache-2.0 model), the seed with the
  least 1–4 kHz energy.
- Voice defaults come from a measured Chirp3-HD A/B (evidence: `C:/Projects/namo-review/voice_ab*`): Kore = highest
  2–5 kHz presence, low sibilance (explainers); Charon = deepest, median F0 84 Hz (shloka/webshow).

## EGM loop (phone only)
`namo/egm.py` runs Elephant-Goldfish against the phone-local proxy `127.0.0.1:8322` (CLIProxyAPI under proot; CI
cannot reach it). Goldfish = one call, no history, a spec + 1–3 files; Elephant = same model with context, may patch;
a patch is kept only if blockers strictly decrease. Budget: one doc + ≤ 3 source files (~20 KB), 3000 tokens, 180 s.
If the proxy is down, start it as the shell uid (the app uid cannot write `/data/local/tmp/agent/cpa/`):
```bash
cd /data/local/tmp/agent && nohup env LD_LIBRARY_PATH=$PWD/proot \
  PROOT_LOADER=$PWD/proot/loader PROOT_TMP_DIR=$PWD/tmp \
  SSL_CERT_FILE=$PWD/proot/ca-bundle.crt \
  $PWD/proot/proot -b $PWD/proot/resolv.conf:/etc/resolv.conf \
  $PWD/np/cli-proxy-api -config $PWD/cpa/config8322.yaml >> $PWD/cpa/proxy8322.log 2>&1 &
```
Key name: `zafiro-local-key` (in `cpa/config8322.yaml`).

## Tried and rejected — do not repeat
- Prompting a video with an LLM; Jev/agentic browser as renderer (~2 s/frame, not deterministic).
- Manim (math-only), Remotion (free only ≤ 3 employees), `stillmotion`, `html-to-video-skill`, `ft-motion` alone.
- `thecodacus/rendiv` was adopted as `rd` for explainers; `mg` stays for ink-wash cards.

## Ground rules
1. Never claim a film passed without `verify_video()` output.
2. Never weaken a check to make a finding disappear; fix the threshold, never `except: return True`.
3. No second repo or second tool: check what exists first.
4. A runtime that cannot honour the brief refuses the job.
5. Run `python namo/drift.py` (and the goldfish when the phone is up) before saying "done".
