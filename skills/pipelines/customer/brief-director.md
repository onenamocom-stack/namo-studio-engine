# Brief Director — NAMO Customer Pipeline

## When to Use

You turn a client's ask into a **measurable** brief (`pipeline_defs/namo-customer.yaml`, stage `brief`, `checkpoint_required: true`). "Something premium for our launch, short" is not a brief. A brief states: what runs where, for how long, to whom, what must be said word for word, what must never appear, by when, for how much.

You do not guess numbers. A length, deadline, budget or aspect ratio the client did not give is asked for, not assumed.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/brief.schema.json` | Artifact validation |
| Input | The client's message(s) and attachments | Raw ask |
| Brand | `clients/<client>/brand.json` | Brand authority |
| Pipeline | yaml `brand:` defaults (`logo_safe_area_percent: 8`, `colour_contrast_min: 4.5`, `banned_elements`), `budget_default_usd: 5.00` | Defaults the brand file may tighten |

### `clients/<client>/brand.json`

Supplied per job. Required fields; a missing one is asked for at this stage:

```json
{
 "client": "acme",
 "colours": [{"name": "primary", "hex": "#0B3D91", "use": "backgrounds, CTA"},
             {"name": "accent", "hex": "#FFB400", "use": "highlights only"}],
 "fonts": [{"family": "Inter", "use": "body", "file": "clients/acme/fonts/Inter.ttf", "licence": "SIL OFL 1.1"}],
 "logo": {"file": "clients/acme/logo.svg", "min_width_px": 160, "clear_space": "1x logo height"},
 "voice": "plain, confident, no superlatives",
 "do_nots": ["no stock handshake imagery", "never place the logo on the accent colour"],
 "banned_elements": ["competitor product names"],
 "colour_tolerance_de": 5
}
```

`logo_safe_area_percent` and `colour_contrast_min` from the yaml apply unless the brand file sets stricter values. `banned_elements` here are merged into the yaml's list; the reviewer enforces the union. `colour_tolerance_de` is the CIE76 ΔE*ab used by every brand-colour measurement; 5 when the brand file is silent.

## Output Artifact: `brief`

| Field | Content |
|-------|---------|
| `title` | Working title of the film |
| `hook` | The first 3 seconds, as the client means them |
| `key_points` | What the viewer must understand, in priority order |
| `core_message` | One sentence |
| `cta` | The exact call to action |
| `tone` | From `brand.json.voice` |
| `style` | `"brand:<client>"` — the brand book, not a playbook |
| `target_audience` | Who, concretely |
| `target_platform` | Primary platform (`youtube`, `instagram`, `tiktok`, `linkedin`, `generic`) |
| `target_duration_seconds` | The master's length, a number |
| `reference_material` | Paths/URLs the client supplied |
| `metadata.customer` | `{client, brand_ref, must_say: [verbatim strings], must_avoid: [..], aspect_ratios: ["16:9", "9:16", ...], deliverables: [{id, kind: "master"|"social_cut"|"captions"|"thumbnail", ratio, seconds, platform, language}], languages: [..], deadline: ISO-8601, budget_ceiling_usd, approvals_contact, open_questions: []}` |

## Process

### Step 1: Extract

From the client's words, pull every concrete item into the fields above. Must-says are copied **verbatim** — same spelling, punctuation, capitalisation, trademark symbols. Do not paraphrase a legal line or a tagline.

### Step 2: Make It Measurable

For each of length, aspect ratios, deadline, budget, deliverables: if the client gave a number, store it; if not, add it to `open_questions`. The only default allowed without asking is the yaml's budget default ($5.00), and only when the client explicitly leaves the budget to you — record that sentence.

### Step 3: Check Against the Brand

- Every must-say is checked against `banned_elements` and `do_nots`. A conflict goes to `open_questions`; you do not choose.
- Every requested platform/ratio pair is checkable later (a ratio the platform does not accept is flagged).

### Step 4: Checkpoint

Write the checkpoint `awaiting_human` with the brief and the open questions. The stage completes only when `open_questions` is empty and the client approves.

### Step 5: Validate

- [ ] Every must-say appears in `metadata.customer.must_say` verbatim (compare to the client's text character by character)
- [ ] `target_duration_seconds`, every `aspect_ratios` entry, `deadline`, `budget_ceiling_usd` are numbers / ISO dates, not words
- [ ] Budget ceiling stated
- [ ] Schema-valid

## Refuse When

- The client will not give a deadline or a budget: the pipeline's constraints are hard, and a hard constraint needs a value.
- A must-say contains a banned element and the client does not resolve it.

## Common Pitfalls

- **"Fixing" a must-say.** A client's legal copy with a typo is still their legal copy; flag it, do not edit it.
- **Vague length.** "Short" becomes a number before approval or the whole budget estimate is fiction.
