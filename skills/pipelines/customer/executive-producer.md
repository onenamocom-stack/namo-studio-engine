# Executive Producer — NAMO Customer Pipeline

## When to Use

You run one client video end to end (`pipeline_defs/namo-customer.yaml`, `orchestration.skill`): brief → concept → script → storyboard → assets → edit → compose → deliver. A client buys a film, not a style: the client's brand book overrides every playbook, and **budget and deadline are hard constraints** (`budget_hard: true`, `deadline_hard: true`). Exceeding either fails the run; it does not warn.

You hold the job state, run each director, review its artifact against the yaml's `success_criteria`, take the work to the client at the three checkpoints, and stop the job the moment money or time runs out.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Pipeline | `pipeline_defs/namo-customer.yaml` | Stages, checkpoints, budget, limits, `brand:` defaults |
| Brand | `clients/<client>/brand.json` (fields defined in `brief-director`) | Colours, fonts, logo, do-nots, banned elements |
| Cost | `tools/cost_tracker.py` `CostTracker` (`estimate` → `reserve` → `reconcile`/`refund`; raises `BudgetExceededError`), artifact `cost_log` | Hard budget |
| Checkpoints | `skills/meta/checkpoint-protocol.md`, `lib/checkpoint.py` | Client approvals (`awaiting_human`) |
| Skills | the eight `pipelines/customer/*-director` skills, `meta/reviewer` | Stage procedures |

## Phase 0: Preflight

1. `python namo/engine.py pipeline pipeline_defs/namo-customer.yaml` → `PASS`.
2. `clients/<client>/brand.json` exists and parses. No brand file → the job does not start (the yaml makes the brand book the authority; there is nothing to defer to).
3. Initialise:

```
JOB_STATE:
  client: <id>                      project_id: <client>-<job>
  budget_cap_usd: <brief budget ceiling, else yaml budget_default_usd 5.00>
  deadline: <ISO-8601 from the brief>
  started_at: <ts>                  max_wall_time_minutes: 120
  revision_counts: {}               # stage -> n, max 2 (client revisions count too)
  approvals: {brief, concept, storyboard, edit}
  cost_tracker: CostTracker(budget_total_usd=budget_cap_usd, mode=BudgetMode.CAP,
                            cost_log_path=projects/<project_id>/cost_log.json)
                                    # default mode is WARN; budget_hard needs CAP
  artifacts: {brief, proposal_packet, decision_log, script, scene_plan, asset_manifest, edit_decisions, render_report, final_review, delivery_log, cost_log}
```

## Phase 1: Stages

For each stage: load the director, inject `JOB_STATE` (remaining budget, time to deadline, brand), receive the artifact, then:

1. Validate against its schema (`schemas.artifacts.validate_artifact(name, data)`; `delivery_log` validates as `publish_log`).
2. Check every yaml `success_criteria` line for the stage as a measured fact.
3. Cross-stage checks (below).
4. Checkpoint. Stages with `checkpoint_required: true` — `brief`, `concept`, `edit` — plus `storyboard` (its success criteria require a client-approved picture) are written `awaiting_human` and wait for the client's answer. A client "approve with changes" is a revision.

**Revisions.** `max_revisions_per_stage: 2`. A third revision request is a change order: stop, state what it costs in money and time, and continue only on a new approved budget/deadline recorded in `decision_log` (`category: budget_tradeoff`, `user_approved: true`). Never absorb it silently.

## Hard Budget

- Before any paid call, the director calls `cost_tracker.estimate(tool, operation, usd)` then `reserve(entry_id)`; after it, `reconcile(entry_id, actual_usd)`; on failure `refund`. `BudgetExceededError` ends the run with `cost_log` written. `reserve` also raises `ApprovalRequiredError` for a tool's first paid use and for any single action above `single_action_approval_usd` (default $0.50): call `approve_tool(tool)` only for tools in the client-approved `production_plan`, and take any single action above the threshold to the client.
- At every gate: `budget_spent_usd + estimate_of_remaining_stages <= budget_cap_usd`, else stop before the next paid stage — finishing over budget is the failure the yaml forbids.

## Hard Deadline

At every gate compute `time_left = deadline − now` and the remaining stages' time from the concept's estimate. `time_left < remaining` → stop and tell the client now, with what can still be delivered by the deadline. Client wait time at checkpoints counts against the deadline; say so when you hand them a checkpoint.

## Cross-Stage Checks

| After | Check | Fail → |
|-------|-------|--------|
| brief | Every must-say verbatim; length, aspect ratios, deadline, budget numeric | revise brief (ask the client) |
| concept | 3 concepts that differ in structure *and* visual approach; each with cost and time; client picked one; decision logged | revise concept |
| script | Every must-say verbatim in `sections[].text`; no must-avoid / banned element; measured length within 2 % of target | revise script |
| storyboard | One rendered still per scene; brand colours measured on each; text contrast ≥ 4.5; client approved | revise storyboard |
| assets | `cost_log` ≤ cap; every asset has a traceable commercial licence; music explicitly cleared for commercial use | revise assets |
| edit | Every scene covered; logo inside the safe area; client approved the preview | revise edit |
| compose | Every requested aspect ratio rendered; zero black frames; brand colours measured on output frames; `final_review.status == pass` | revise compose / send back |
| deliver | Every deliverable in the brief present and verified; licence manifest complete | revise deliver |

## Refuse the Job When

- No brand file, or the brief cannot be made measurable (no budget, no deadline, no length) after asking the client.
- The cheapest concept already exceeds the budget or cannot meet the deadline.
- A brand rule and a must-say conflict (e.g. a banned element named in a must-say): stop and ask; do not pick.

## Common Pitfalls

- **Treating the budget as advisory.** `budget_hard` means the run fails, so the check happens *before* spending.
- **Hiding checkpoint wait time.** The deadline does not pause while the client thinks.
- **Letting a playbook override the brand.** `brand.override_playbook: true` — the playbook fills only what the brand book leaves open.
