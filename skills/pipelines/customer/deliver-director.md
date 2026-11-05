# Deliver Director — NAMO Customer Pipeline

## When to Use

You hand the client everything the brief bought (`pipeline_defs/namo-customer.yaml`, stage `deliver`): **master + social cuts + captions + thumbnails + a one-page licence manifest**, each verified, before the deadline. Produces `delivery_log`.

There is no `delivery_log` schema of its own: it is a `publish_log`-shaped artifact (one entry per delivered file) and is validated with `validate_artifact("publish_log", delivery_log)`. You do not post to the client's channels; you deliver files.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Validation of `delivery_log` |
| Prior artifacts | `render_report` (outputs per deliverable), `final_review` (must be `pass`), `brief` (`metadata.customer.deliverables`, `languages`, `deadline`) | What to deliver |
| Upstream | `edit_decisions` (caption cues), `asset_manifest` (`metadata.customer.licences`), `cost_log` | Captions, licences, spend |
| Tool | `export_bundle` (per video deliverable; it copies video + subtitle + thumbnail and returns a valid `publish_log` entry) | Packaging |

## Gate Before Anything

`final_review.status == "pass"` and `now < brief.metadata.customer.deadline`. A failed review → nothing is delivered. A missed deadline → the executive producer tells the client before you deliver late; the log records it.

## Deliverables

Layout under `projects/<project_id>/delivery/`:

```
video/<deliverable_id>.mp4          master and every social cut, one per brief deliverable
captions/<deliverable_id>.<lang>.srt one per video deliverable per brief language
thumbnails/<deliverable_id>.png      one per video deliverable, at its ratio
LICENCES.md                          the one-page licence manifest
SHA256SUMS                           every file above
```

## Process

### Step 1: Collect and Check Videos

For each video deliverable in the brief: take the matching `render_report.outputs[]` file. Re-probe it (`ffprobe`), compare ratio and duration to the deliverable, and copy it under its deliverable id. A deliverable with no output is a stage failure — send back to compose.

### Step 2: Captions

From the edit's subtitle cues, write an `.srt` per deliverable per language with times in that deliverable's timeline (cut-downs re-timed). Check: every narration line has a cue; cues do not overlap; text matches the script (must-says verbatim).

### Step 3: Thumbnails

One frame per video deliverable at its ratio, picked from the film (a frame the client already approved in the storyboard is the default). Measure with `brand_share()` / `contrast()` (storyboard-director Step 3): brand colours present, any text ≥ 4.5 contrast, logo inside the safe area. Never a picture the film does not contain.

### Step 4: Licence Manifest (one page)

`LICENCES.md`, built from `asset_manifest.metadata.customer.licences`: a table of every third-party element — asset, source/provider, licence, commercial-use evidence URL, attribution text, restrictions. Required lines when they apply:

- MiniMax H3 footage: "Video generated with MiniMax H3" and the AI-generated-content disclosure the client must keep.
- Any attribution-required licence: the exact attribution text the client must publish.
- Client-provided assets: listed as client-provided.

One page: if it does not fit, group identical licences; never drop a row.

### Step 5: Package and Hash

Run `export_bundle` per video deliverable (`video_path`, `title`, `subtitles_path` = its primary-language `.srt`, `thumbnail_path`, `platform: "client_handoff"`, `visibility: "private"`); copy additional-language captions alongside. Write `SHA256SUMS` over the delivery tree and verify it (`sha256sum -c SHA256SUMS`).

### Step 6: `delivery_log`

One entry per delivered file:

```json
{"version": "1.0",
 "entries": [{"platform": "client_handoff", "status": "exported",
              "export_path": "projects/<project_id>/delivery/", "timestamp": "<ISO-8601>",
              "metadata_used": {"deliverable_id": "<id>", "file": "video/<id>.mp4", "sha256": "<hash>", "duration_seconds": <probed>}}],
 "metadata": {"customer": {"client": "<id>", "deadline": "<ISO-8601>", "delivered_at": "<ISO-8601>", "on_time": true,
                           "total_cost_usd": <cost_log completed spend>, "budget_cap_usd": <cap>, "licence_manifest": "LICENCES.md"}}}
```

Validate with `validate_artifact("publish_log", delivery_log)`.

### Step 7: Self-Check

- [ ] Every brief deliverable present: master, each social cut, captions per language, thumbnails, `LICENCES.md`
- [ ] Every video re-probed against its deliverable spec
- [ ] `SHA256SUMS` verified
- [ ] `total_cost_usd ≤ budget_cap_usd`, `on_time` measured
- [ ] Licence manifest covers every asset in the manifest

## Refuse When

- `final_review` is not `pass`, or any deliverable is missing or off-spec.
- An asset in the film has no licence row: the manifest is the client's proof of rights; an incomplete one is not delivered.

## Common Pitfalls

- **Captions on the master's timeline for a cut-down.** Re-time per deliverable.
- **Thumbnails generated, not taken from the film.**
- **A licence manifest that says "various"**: the client's legal team needs each source.
