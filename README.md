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
| mg | cpu | 0 | vector motion graphics (lemo, 68 styles, via ft-motion) |
| h3 | gpu | $0.00039/s | MiniMax H3 image-to-video (outsourced) |

## Current state
Read `SPEC.md` -> "Known drift". Last measured: `agent.py` borrows the webshow scene for
every kind (D4), 15 pipeline skill references have no file (D1-D3), R2 creds return 401 (D5).
The studio is being built, not finished.
