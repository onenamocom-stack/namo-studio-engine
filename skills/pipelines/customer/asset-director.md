# Asset Director — NAMO Customer Pipeline

## When to Use

You produce every asset of the approved storyboard (`pipeline_defs/namo-customer.yaml`, stage `assets`) inside a **hard** budget, and you make every asset's licence traceable and commercially clear. A client film ships in ads, on paid placements, on the client's site: an asset you cannot prove the client may use commercially is an asset you do not use. Produces `asset_manifest` (and keeps `cost_log` current).

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/asset_manifest.schema.json`, `cost_log.schema.json` | Validation |
| Prior artifacts | `scene_plan` (`required_assets`, approved stills), `script` (sections, measured timing), `proposal_packet` (`production_plan`: tools, voice, music source) | What to make, with what |
| Cost | the executive producer's `CostTracker` (mode `CAP`) | Hard budget |
| Tools | `tts_selector`, `image_selector`, `video_selector`, `music_gen` and the approved providers only | Generation |
| Brand | `clients/<client>/brand.json` (fonts with licences, logo file) | Client assets |

## Output Artifact: `asset_manifest`

One `assets[]` entry per file:

| Field | Content |
|-------|---------|
| `id`, `type`, `path`, `scene_id`, `source_tool` | As usual |
| `provider`, `model`, `prompt`, `seed` | Exactly what produced it, so it can be reproduced |
| `cost_usd` | The reconciled actual, from the cost tracker |
| `duration_seconds`, `resolution`, `format` | Measured with ffprobe / Pillow |
| `license` | The licence by name + the commercial-use basis, e.g. `"client-provided (brand.json)"`, `"<provider> terms: commercial use of outputs permitted — <terms URL>"`, `"<stock licence> — <licence URL>"` |
| `original_url` | Source page for any sourced (stock/library) asset |
| `total_cost_usd` | Sum; must equal `cost_log` completed spend |
| `metadata.customer.licences[]` | `{asset_id, licence, commercial_use: true, attribution_required: bool, attribution_text, evidence_url, restrictions}` — the input for the delivery's licence manifest |

## Process

### Step 1: Inventory and Budget

List every required asset from the scene plan. Price each paid one with the tool's estimate. If `spent + estimates > budget_cap_usd`, stop now and give the executive producer the savings options from the proposal — do not start generating and hope.

### Step 2: Client Assets

Logo, fonts, product shots, footage the client supplied: copy into the project, record `license: "client-provided"` and the file's origin. Fonts: the licence in `brand.json.fonts[].licence` must allow video embedding; if it is not stated, ask.

### Step 3: Generate / Source, One Paid Call at a Time

For each paid asset: `estimate` → `reserve` → call → `reconcile(actual)` (or `refund` on failure). `BudgetExceededError` or `ApprovalRequiredError` stops the stage and goes to the executive producer. Prompts carry the brand colours (hex), the brand do-nots as negatives, and match the approved still.

### Step 4: Licence Gate (every asset)

An asset passes only if all are true:

- The licence is **named** and its commercial-use permission is evidenced by a URL or a document (provider terms, stock licence, client statement).
- **Music**: cleared explicitly for commercial use in advertising / client work. "Royalty free" alone is not a clearance. Generated music: the model's licence must grant commercial use of outputs — record which licence and where it says so.
- **Not usable for client work**: anything under a non-commercial licence (CC BY-NC*, research-only model licences), ND licences when the asset is modified, unknown-origin files, and Wav2Lip (non-commercial licence — the handoff flags it for replacement).
- **MiniMax H3** clips: usable only with the credit "MiniMax H3" shown and AI-generated content disclosed — record both as `restrictions`; the deliver stage puts them in the licence manifest.
- **Voices**: a TTS voice's terms must allow commercial use; cloned voices only with the speaker's written consent on file.

### Step 5: Verify

- Every file exists, decodes (ffprobe for audio/video, Pillow for images), and matches its scene (images compared with the approved still: same composition, brand colours measured with the storyboard method).
- Narration: measured durations within the script's sections.
- `total_cost_usd` = `cost_log` completed spend ≤ `budget_cap_usd`.

### Step 6: Submit

- [ ] Cost tracker never exceeded the hard budget
- [ ] Every asset has `license` + `metadata.customer.licences[]` entry with `commercial_use: true` and evidence
- [ ] Music is cleared for commercial use, by name and evidence
- [ ] Schema-valid

## Refuse When

- An asset's licence cannot be evidenced: replace it (within budget) or report it; never ship it.
- The remaining budget cannot cover the remaining assets.

## Common Pitfalls

- **"Royalty free" as a licence.** It says who is paid, not what use is allowed.
- **Spending first, checking the cap after.** The tracker reserves before the call for a reason.
- **Losing provenance.** An asset without provider, model and prompt cannot be re-made when the client asks for a change.
