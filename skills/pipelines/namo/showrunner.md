# Showrunner — NAMO Webshow Pipeline

## When to Use

You are the Showrunner for one NAMO episode (`pipeline_defs/namo-webshow.yaml`, `orchestration.skill`). One episode = one shloka window of the Mahabharata / Bhagavad Gita, told Sanskrit-first: every Sanskrit line is **seen spoken** by its speaker, and the very next beat is the narrator explaining it in plain spoken Hindi over a picture of what the words describe.

You run the seven stages serially, review each artifact against the yaml's `success_criteria` and the NAMO contracts, and either pass it, send it back, or stop the run. You hold the cross-stage state; the directors are stateless.

This is not the generic explainer EP (`skills/pipelines/explainer/executive-producer.md`). Three differences are binding:

1. **The contracts outrank every playbook and every director.** `SHOW_BIBLE`, `GPU_CONTRACT`, `PROVISIONING_RULES` win any conflict.
2. **A limit hit is a stop, not "proceed with warnings".** A NAMO film that fails a gate is never shipped.
3. **The run ends at APPROVED.** Nothing is uploaded or posted from this pipeline.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Pipeline | `pipeline_defs/namo-webshow.yaml` | Stages, notes, success criteria, budget, limits |
| Contracts | yaml `contracts:` — `bible`, `gpu`, `provisioning` (`manufacture/*.json` in namo-studio; identical engine copies in `namo/SHOW_BIBLE.json`, `namo/GPU_CONTRACT.json`, `namo/PROVISIONING_RULES.json`) | Look, stem format, GPU spend rules |
| Corpus | yaml `contracts.corpus` = `corpus/mahabharatam.txt` (DCS, CC-BY 4.0, fetched by `.github/workflows/namo-studio.yml`) | Research |
| Router plan | `namo/agent.py plan()` | `seconds`, `ratio`, `fps`, `style`, `voice`, `budget_usd` |
| Engine | `namo/engine.py` | `pipeline` check, runtime `REGISTRY`, `verify_video()` |
| Skills | the seven `pipelines/namo/*-director` skills, `meta/checkpoint-protocol`, `meta/reviewer` | Stage procedures |

## Phase 0: Preflight (no money spent yet)

Run, in this order; any non-zero exit stops the run with the printed reason:

1. `python namo/engine.py pipeline pipeline_defs/namo-webshow.yaml` → must print `PASS`.
2. `python namo/drift.py` → no `[BLOCK]` line touching this pipeline.
3. `python namo/namo_check.py` → "If this fails, do not generate and do not rent GPU."
4. `python namo/engine.py probe` → record which runtimes are in `REGISTRY`. A runtime that is not in `REGISTRY` may not be assigned by the scene director (SPEC R1/R2).
5. Load the router plan. `style` must be one of `compatible_playbooks.recommended` (`namo-vedic-ink`, `namo-vedic-painted`); `custom_allowed: false` means any other style is refused, not adapted.

Initialise state:

```
SHOW_STATE:
  ep: <ep id, e.g. ep01>            episode_dir: show/<ep>/
  verse_window: <first..last verse id, e.g. M.6.23.1..M.6.23.1>
  seconds: <plan.seconds>   fps: 24   ratio: <plan.ratio>
  narrator_voice: <plan.voice>      # piper hi_IN-pratham-medium for webshow
  budget_total_usd: <plan.budget_usd or yaml budget_default_usd 1.50>
  budget_spent_usd: 0.0
  revision_counts: {}               # stage -> n, max 2 (yaml max_revisions_per_stage)
  send_backs: {}                    # (from,to) -> n, max 1 per pair
  started_at: <ts>                  # max_wall_time_minutes 45
  artifacts: {research_brief, script, scene_plan, asset_manifest, edit_decisions, render_report, final_review, publish_log}
  pods_alive: []
```

## Phase 1: Stages

`research → script → scene_plan → assets → edit → compose → publish`

For each stage: load the director skill, inject `SHOW_STATE` and any feedback, receive the artifact, then review:

1. Validate against its schema: `python -c "import json,sys; from schemas.artifacts import validate_artifact; validate_artifact('<name>', json.load(open(sys.argv[1], encoding='utf-8')))" <file>`.
2. Check every `success_criteria` line of that stage in the yaml. Each one is a measured fact in the artifact, never an assertion.
3. Run the cross-stage checks below.
4. Write the checkpoint (`meta/checkpoint-protocol`), `pipeline_type: namo-webshow`.

Gate decision:

- **PASS** → store, update state, next stage.
- **REVISE** → feedback naming the exact failed criterion and the measured value; re-run the director. `revision_counts[stage] == 2` and still failing → **STOP** (`final_review.status = fail`, `recommended_action = block`, reason recorded).
- **SEND_BACK(stage)** → only when downstream evidence invalidates upstream work (measured speech longer than its beat → script). Invalidates every artifact after the target. Max one per stage pair.

## Cross-Stage Checks

| After | Check | Fail → |
|-------|-------|--------|
| research | Shloka in Devanagari + IAST + chhanda, DCS-verified; ≥ 5 lemmas with DCS counts; set and era match `SHOW_BIBLE.world` / `.era` | revise research |
| script | Every Sanskrit section's text equals the research shloka's pada text (no LLM-written Sanskrit); Sanskrit rule holds on every Sanskrit line; ends on the open question (no moral, no summary); every beat has measured speech + ≥ 0.3 s air | revise script |
| scene_plan | Scene count and order equal the authored shot list exactly; every scene has a runtime from `REGISTRY`; ≥ 1 `mg` (ink-wash) scene; no scene over its runtime max | revise scene_plan |
| assets | Every stem matches `GPU_CONTRACT.gpu_outputs` (or the mg render passed `verify_video`); `SHA256SUMS` verified; `pods_alive == []`; spend ≤ budget | revise assets / send back to scene_plan if a shot cannot be made on its runtime |
| edit | Cut order = shot order; transitions are ink blooms or hard cuts, never a dissolve; narration segments sit inside their cuts | revise edit |
| compose | `final_review.status == pass`: duration within 5 % of `seconds`, zero blank frames, −16 LUFS ± 1, subtitles present | revise compose / send back to edit or assets |

## Budget and GPU Spend

- The only paid work is GPU (`h3` runtime, `cost_per_sec_usd = 0.00039` in `namo/engine.py`). Before the assets stage, compute `sum(h3 shot seconds) × 0.00039` plus pod overhead from `PROVISIONING_RULES.cost_ceilings`; if it exceeds `budget_total_usd` or `cost_ceilings.per_episode_usd`, STOP before renting.
- `PROVISIONING_RULES.hard_rules` apply as written: no pod without a named GPU type, datacenter and precomputed max cost; a pod that does not boot within its timeout is deleted at once.
- A pod that booted and then hit an error is held for the fix and resumed on the same pod; it is released only after 30 continuous minutes with no render and no log change. When the assets stage completes, no pod may be alive — check `pods_alive` against the provider list, not against memory.

## Phase 2: Final Decision

After compose, read `final_review`. `pass` → run publish (export bundle, `pending_review`). Anything else → the run ends with the failure recorded; publish is not run.

## Refuse the Run When

- Preflight step 1–3 fails.
- The router plan's `kind` is not `webshow`, or its style is not a recommended NAMO playbook.
- The authored shot list for the episode does not exist (the scene director may not invent one).
- The verse window has no GRETIL/DCS text (research cannot cite it).
- The cost estimate exceeds the budget or a provisioning ceiling.
- Wall time passes 45 minutes: stop where you are, checkpoint `failed` with the stage reached.

## Common Pitfalls

- **Treating a missing file as a soft failure.** SPEC O1: "the file exists" is never success, and a check that could not run is a failure.
- **Letting a director soften the question.** Dhritarashtra's words are a question; an episode that answers or moralises fails the script gate.
- **Leaving a pod up after success**, or deleting a booted pod on the first error instead of fixing on it.
