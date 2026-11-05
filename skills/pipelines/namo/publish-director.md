# Publish Director — NAMO Webshow Pipeline

## When to Use

You package an approved episode for the owner (`pipeline_defs/namo-webshow.yaml`, stage `publish`). **The pipeline ends at APPROVED. The owner does not publish from here.** You do not upload to YouTube, Instagram, R2 or anywhere else; you produce a local export bundle with everything the owner needs to review and post it, and a `publish_log` that says it is waiting for him.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `render_report` (`outputs[].path`), `final_review` (`status`) | What to package; whether to |
| Upstream | `script` (`title`, `metadata.namo`), `research_brief` (verse ids, sources), `asset_manifest` (licences, runtimes used) | Metadata and credits |
| Tool | `export_bundle` (yaml `tools_available`) — writes `video/`, `metadata/`, `thumbnails/` and returns a schema-valid `publish_log` | Packaging |

## Gate Before Anything

`final_review.status` must be `pass`. Anything else: do not package; write nothing; return the review's `issues_found` to the showrunner.

## Process

### Step 1: Metadata

- `title`: the episode's Hindi title; add the verse reference (`गीता 1.1` / `M.6.23.1`). Keep the Sanskrit title (`title_sa`) and English title (`title_en`) in `description`.
- `description`: the hook in Hindi, then the spoken verses (Devanagari + verse id), then credits:
  - "Sanskrit text: GRETIL e-text of the BORI critical edition."
  - "Word data: Digital Corpus of Sanskrit (DCS), CC-BY 4.0." (attribution is a licence condition)
  - If any `asset_manifest` asset has `source_tool: engine.h3`: "Video generated with MiniMax H3. This film contains AI-generated content." (H3 licence: commercial use must show "MiniMax H3" and disclose AI generation.)
- `tags` / `hashtags`: names and places that actually occur in the verses (from `research_brief.metadata.namo.lemmas`), plus `Mahabharata`, `Bhagavad Gita` where true. No trend-bait.
- `chapters`: none for a sub-2-minute episode.

### Step 2: Thumbnail

Pick a frame, never generate a new picture: the first Sanskrit line's shot at its midpoint (the speaker, lit by fire). Extract with `ffmpeg -ss <t> -i final.mp4 -frames:v 1 thumbnail.png`. No text burned onto it — the title travels as metadata.

### Step 3: Export

Call `export_bundle` with `video_path` = `render_report.outputs[0].path`, `title`, `description`, `tags`, `hashtags`, `subtitles_path` = the Hindi `.srt`, `thumbnail_path`, `platform: "local"`, `visibility: "private"`, `project_name: "namo-<ep>"`. It refuses a missing subtitle or thumbnail file — fix the path, do not drop the file.

Copy the English sidecar (`final.en.srt`) into the bundle's `video/` as `subtitles.en.srt` (`export_bundle` takes one subtitle file).

### Step 4: Build `publish_log`

Start from the tool's returned `publish_log` (one entry, `status: "exported"`, `export_path`). Append one entry:

```json
{"platform": "owner_review", "status": "pending_review", "visibility": "private",
 "export_path": "<same export path>", "timestamp": "<ISO-8601 now>"}
```

Put `{"ep": "<ep>", "verses": [...], "final_review_status": "pass", "integrated_lufs": <from final_review.metadata.namo>}` in `metadata`. Validate against the schema.

### Step 5: Self-Check

- [ ] `final_review.status == "pass"` was read, not assumed
- [ ] Bundle contains the video, Hindi + English subtitles, metadata, thumbnail
- [ ] Credits present; AI disclosure present whenever H3 was used
- [ ] No entry with `status: "published"` and no URL — nothing left the machine

## Refuse When

- `final_review.status` is not `pass`.
- Asked to upload or post: this pipeline has no publish step by design; return the export path for the owner.
- A credit cannot be written because a source is unknown (an asset without a `license`): send back to assets.

## Common Pitfalls

- **"Helpfully" uploading.** The owner approves and posts; the run never does.
- **Dropping the DCS attribution.** CC-BY makes it a condition, not a courtesy.
- **A generated thumbnail** that shows something the film does not.
