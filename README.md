# NAMO Studio Engine

One prompt in, one video out. Built on OpenMontage; owned by NAMO.

## Start here
1. **`SPEC.md`** — the contract. Every invariant, every known drift, measured.
2. **`namo/agent.py`** — the router: a brief becomes a plan, deterministically.
3. **`namo/engine.py`** — the one door: runtimes register here, nothing calls a renderer directly.
4. **`namo/drift.py`** — the goldfish: fails CI when the repo stops matching SPEC.md.

## Run it
```bash
bash namo/bootstrap.sh                        # clone engines, fetch fonts, venv
python3 namo/engine.py runtimes --probe       # is anything actually ready?
python3 namo/drift.py                         # does the repo match the spec?
python3 namo/agent.py --dry "40 sec vertical explainer about Jev mode"
python3 namo/agent.py "40 sec vertical explainer about Jev mode"
```
Or from GitHub: **Actions -> namo-agent -> Run workflow**, one prompt, watch the artifact.

## Design review (EGM)
`skills/egm/` carries Google's Elephant-Goldfish Model skills (Apache-2.0, imported from
`google/elephant-goldfish-model`): bootstrap holds context, draft writes the spec,
review runs fresh-context criticism, **drift-report** compares implementation to spec,
resolve settles findings. `namo/drift.py` is the automated half of drift-report.

## Engines
| runtime | kind | cost | what |
|---|---|---|---|
| mg | cpu | 0 | lemo ink-wash motion graphics (webshow cards, `namo/mg/scenes/`) |
| rd | cpu | 0 | rendiv explainers (`namo/rd/beats/`) |

GPU (MiniMax H3) episodes are not an engine runtime: they are made by
`onenamocom-stack/namo-studio`. The operating manual for both repos is
`namo-studio/FACTORY_MANUAL.md`.

## Current state
`HANDOFF.md` (engine notes) and `SPEC.md` -> "Known drift".
