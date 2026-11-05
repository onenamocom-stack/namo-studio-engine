# program.md — the research org for the NAMO studio engine

This file is the only thing a human edits. The elephant agent reads it and runs the loop.
Modeled on karpathy/autoresearch: the agent edits code, a fixed-budget run scores it,
good changes are kept, bad ones are reverted, repeat.

Adapted because a video is not a training run: there is no loss curve. The score comes from
a fresh-context goldfish reviewer, which is why the reviewer must never share context with
the fixer.

---

## The two roles, and why they must not be the same process

**ELEPHANT** holds context. It has read the spec, the reviews, the decisions. It is the only
role allowed to write code. It will defend its own work; expect that and it is fine.

**GOLDFISH** has no context. It receives a design document and source files. It does not know
what was intended, so it cannot forgive an unstated assumption. Its only job is to say what
is actually broken.

The loop only works because these are separate calls with separate message histories.
A review run in the same context is not a review.

---

## The loop

```
for round in 1..N:
    corpus   = the files under review (small, bounded — see Budget)
    review   = GOLDFISH(doc + corpus)              fresh context, no history
    blockers = count of numbered findings under ## BLOCKERS
    if blockers == 0: stop, keep the current tree
    patch    = ELEPHANT(review + corpus + decisions)   has context, may write code
    apply patch to a working copy
    re-review with GOLDFISH                        same corpus, fresh context again
    if new_blockers < old_blockers: keep
    else: revert (the patch did not help, or made it worse)
```

The revert branch is the point. Without it the loop is just a sequence of edits with a
reviewer that nobody listens to.

---

## Budget — this is what went wrong before

A 54 KB corpus in one call produced a 23,000-token prompt, 5,500 reasoning tokens, and a
timeout at 400 s. The EGM contract already warned about this; it was ignored.

Rules:
- **One document, at most three source files per call.** If the corpus grows past ~20 KB,
  split the review into passes (one pass per concern: routing, rendering, publishing).
- **max_tokens 3000 for a review, 8000 for a patch.** A review that needs more is a review
  that is reviewing too much.
- **Timeout 180 s.** If a call exceeds it, the corpus was too big. Do not raise the timeout.
- Sequential, never parallel. The buffer is shared.

---

## The metric

There is no scalar loss. The score is, in order:

1. `blockers` — fewer is better. This is the primary metric.
2. `holes` — a claim in the spec with no implementation.
3. `silent_assumptions` — code depending on something nobody wrote.

A change is an improvement only if `blockers` strictly decreases. Tie-breaking on the other
two does not count as progress; treat a tie as no progress and revert.

---

## What the elephant may not do

These produce a green review without producing a working system. They are banned:

1. **Deleting or weakening a check to make a finding disappear.** If `verify_video()` is too
   strict, the fix is a correct threshold, not `except: return True`.
2. **Adding a second path that bypasses the registry.** `engine.REGISTRY` stays the only door.
3. **Writing a refusal and calling it a fix** — for example, refusing every kind that has no
   scene yet. That is honest, but it does not make a film. It must be filed under UNFIXABLE,
   not under CLOSED.
4. **Editing GENESIS** (see below). Anything a human wrote is out of scope.
5. **Claiming a test passed without running it.** Evidence or it did not happen.

---

## GENESIS — read-only

The elephant never edits these. If a fix seems to need a change here, that is an UNFIXABLE
and the question goes to the owner:

- `SPEC.md` — the contract itself. Only the owner changes the contract.
- `pipeline_defs/*.yaml` — only the owner adds or removes a pipeline
- `program.md` — this file

Everything else is fair game: `namo/agent.py`, `namo/engine.py`, `namo/factory.py`,
`namo/drift.py`, `namo/bootstrap.sh`, `.github/workflows/*` that the studio owns.

---

## Fixed budget per round

Mirroring autoresearch's fixed 5-minute training run: each round gets a fixed wall-clock
budget for the review (180 s) and no budget for the patch beyond one model call. The loop does
not run longer because a change is "almost done". It stops and reports.

---

## What to hand back to the owner

At the end of the loop, write `reviews/round-<n>/` with:

- `goldfish.md` — the final review
- `elephant.md` — the patches that were kept, and the ones reverted with the reason
- `unfixable.md` — every finding that needed a decision only the owner can make, phrased as a
  question, not as an excuse

The owner reads `unfixable.md` first. That file is the actual work order.
