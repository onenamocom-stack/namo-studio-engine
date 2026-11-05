# Storyboard Director — NAMO Customer Pipeline

## When to Use

You turn the approved `script` into a frame-accurate storyboard (`pipeline_defs/namo-customer.yaml`, stage `storyboard`) and get the client to approve it. **The client approves a picture, not a description**: every scene has a rendered still, made with the runtime and assets the film will use, and every still is checked for brand colours and text contrast before approval is requested. Produces `scene_plan`.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/scene_plan.schema.json` | Artifact validation |
| Prior artifacts | `script` (sections, measured timings), `proposal_packet` (selected concept, `render_runtime`, playbook) | What each scene shows |
| Brand | `clients/<client>/brand.json` (colours, fonts, logo, `colour_tolerance_de`), yaml `brand.logo_safe_area_percent`, `brand.colour_contrast_min` | Checks |
| Stills | `video_compose` (a one-frame `render` of the scene in the approved runtime), `image_selector` (generated imagery, cost via the tracker) | The pictures |
| Python | Pillow + numpy (in `requirements.txt`) | Measurements |

## Output Artifact: `scene_plan`

| Field | Content |
|-------|---------|
| `style_playbook` | The concept's playbook (it fills only what the brand book leaves open) |
| `scenes[]` | `{id, type, description, start_seconds, end_seconds, script_section_id, framing, movement, transition_in, transition_out, overlay_notes, shot_language, narrative_role, required_assets}` — one per script section, timings from the measured script |
| `metadata.customer.stills[]` | `{scene_id, ratio, path, frame_seconds, brand_colours_expected: [hex], brand_share: {hex: share}, text: [{text, fg_hex, bg_box: [x, y, w, h], bg_rgb, contrast}], logo_box: [x, y, w, h], logo_in_safe_area: bool, banned_hits: [], ok: bool}` |
| `metadata.customer.approval` | `{status: "pending"|"approved"|"approved_with_changes"|"rejected", notes}` |

## Process

### Step 1: Decompose

One scene per script section (split a section only when it holds two visual ideas; record why). `required_assets` lists everything the scene needs, with `source: "provided"` for client assets, `"generate"` for paid generation.

### Step 2: Render a Still per Scene, per Ratio

Render the scene's key frame (the frame at its main beat) in the approved runtime at full resolution, for every aspect ratio in `brief.metadata.customer.aspect_ratios`. Paid imagery goes through the cost tracker (estimate → reserve → reconcile). A still made in a different tool than the film's runtime is not a storyboard — it is a promise compose cannot keep.

### Step 3: Measure Every Still

```python
import numpy as np
from PIL import Image

def _lin(rgb):
    c = np.asarray(rgb, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def lab(rgb):
    xyz = _lin(rgb) @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz = xyz / [0.95047, 1.0, 1.08883]
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

def rgb(hexcode):
    return [int(hexcode[i:i + 2], 16) for i in (1, 3, 5)]

def brand_share(png, hexes, tol=5.0):
    """share of pixels within tol (CIE76 dE*ab) of each brand colour; nearest-neighbour downscale keeps pure pixels."""
    im = Image.open(png).convert("RGB")
    im = im.resize((max(1, im.width // 4), max(1, im.height // 4)), Image.NEAREST)
    px = lab(np.asarray(im, float).reshape(-1, 3))
    return {h: float((np.linalg.norm(px - lab(rgb(h)), axis=1) <= tol).mean()) for h in hexes}

def contrast(fg_hex, bg_rgb):
    """WCAG 2 contrast ratio between a text colour and a measured background colour."""
    l1, l2 = (float(_lin(c) @ [0.2126, 0.7152, 0.0722]) for c in (rgb(fg_hex), bg_rgb))
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
```

- **Brand colours**: `brand_share(still, expected, tol=brand.colour_tolerance_de)`; every colour the scene declares must cover ≥ 1 % of the frame. A declared brand colour that is absent means the render drifted (wrong hex, colour management, grading).
- **Text contrast**: for every text element, `bg_rgb` = the median pixel of a box behind the text with the glyphs excluded (sample beside the text, same background); `contrast(fg_hex, bg_rgb) >= colour_contrast_min` (4.5, WCAG AA). HyperFrames renders also run its built-in WCAG audit during `check`.
- **Logo**: the logo's bounding box lies inside the frame inset by `logo_safe_area_percent` (8 %) on every side, at or above `brand.logo.min_width_px`, never on a colour the brand file forbids.
- **Banned elements**: look at the still; anything in the banned lists or `do_nots` is a fail.

### Step 4: Present

Lay out the stills in order with timings and the narration line under each, per ratio. Write the checkpoint `awaiting_human`. The client's notes are revisions (`max_revisions_per_stage: 2`).

### Step 5: Validate

- [ ] A rendered still exists for every scene and every ratio before approval is requested
- [ ] Every still: brand colours measured and present, every text ≥ 4.5 contrast, logo inside the safe area, no banned element
- [ ] Scenes contiguous and equal to the script's timings
- [ ] Schema-valid; `approval.status` is the client's answer

## Refuse When

- The approved runtime cannot render a still for a scene: report it to the executive producer (concept promised something compose cannot make).
- A brand colour cannot be reproduced within tolerance in the chosen runtime (e.g. a gradient banned by the brand book is the only way to show it).

## Common Pitfalls

- **Approving descriptions.** "Hero shot of the product" is not approvable; the still is.
- **Sampling contrast on the glyphs.** Measure the background beside the text; the text colour is the declared hex.
- **One ratio only.** A 9:16 reframe can push the logo out of the safe area or text off the frame.
