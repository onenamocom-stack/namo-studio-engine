# Corpus Director — NAMO Webshow Pipeline

## When to Use

You are the researcher for one NAMO episode (`pipeline_defs/namo-webshow.yaml`, stage `research`). Research here is **the text itself**: the episode's Sanskrit verses and the DCS-annotated Mahabharata. It is not YouTube, Reddit, blogs or a general web search, and no claim enters the brief without a verse id.

Your output fixes, for everything downstream: which verses are spoken, their exact Sanskrit, the metre, who says them in the text, the words that matter (measured in DCS), and the world they happen in.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/research_brief.schema.json` | Artifact validation |
| Spoken text | GRETIL e-text of the BORI critical edition, Bhishmaparvan: `https://gretil.sub.uni-goettingen.de/gretil/1_sanskr/2_epic/mbh/mbh_06_u.htm` (parsed by namo-studio `manufacture/namo_write.py gretil()`: main text only, half-lines `a`/`c`) | The Sanskrit that is spoken and subtitled |
| Corpus | yaml `contracts.corpus` = `corpus/mahabharatam.txt` — DCS, CC-BY 4.0, fetched from `https://raw.githubusercontent.com/ambuda-org/dcs/master/mahabharatam.txt` by `.github/workflows/namo-studio.yml`; loader namo-studio `vedic/namo_vedic.py` (`Corpus().verse(vid)`, `.devanagari(vid)`, `.search(lemma)`), appearance lookup `manufacture/namo_text.py` | Verse cross-check, lemma counts |
| Bible | `SHOW_BIBLE.json` (`world`, `era`, `evidence`, `banners`) | Location and era |
| Router plan | `ep`, `seconds`, verse window from the brief | Scope |

Verse ids are `M.<parvan>.<adhyaya>.<verse>` (BORI numbering). The Bhagavad Gita is Bhishmaparvan adhyayas 23–40 of the critical edition: Gita chapter *n*, verse *v* is `M.6.(22+n).v`. Confirm every mapping by text match, never by arithmetic alone.

## Output Artifact: `research_brief`

Schema-valid `research_brief` (`version "1.0"`; the schema demands ≥ 3 `existing_content`, ≥ 3 `data_points`, ≥ 3 `common_questions`, ≥ 3 `angles_discovered`, ≥ 5 `sources`). NAMO fields go in `metadata.namo`, because every schema object is closed (`additionalProperties: false`).

| Field | Content |
|-------|---------|
| `topic` | `"<Gita n.v / Mbh> (M.x.y.z): <what happens>"` |
| `landscape.existing_content` | Prior NAMO episodes that touch the window (namo-studio `manufacture/plans/<ep>_episode.json`, `namo/mg/scenes/<scene>/`): what each covers and misses. Not web videos. |
| `landscape.underserved_gaps` | What no NAMO episode has told yet in this window |
| `data_points[]` | One per verse fact or lemma: `claim` quotes the verse id, `source_url` = the GRETIL or DCS URL, `credibility: primary_source` |
| `audience_insights` | The questions a common Hindi viewer has about these verses (who speaks, who is spoken of, why it matters); `misconceptions` only with a verse that corrects them |
| `angles_discovered[]` | `type: narrative` or `evergreen`; `grounded_in` = verse ids + half-line |
| `sources[]` | GRETIL e-text, DCS corpus, `SHOW_BIBLE.json`, `CAST_WEIGHTAGE.json`, `VERSES_HI.json`/`VERSES_EN.json` (reliability `secondary`: their Hindi meanings are LLM-written and need Sanskrit review) |
| `metadata.namo.verse_window` | `[first_id, last_id]` |
| `metadata.namo.shloka[]` | Per spoken half-line: `verse_id`, `half` (`a`/`c`), `iast` (GRETIL), `deva` (IAST → Devanagari, word-final consonant keeps its virama as in `namo_write.deva()`), `syllables`, `dcs_match` (bool), `dcs_text` when it differs |
| `metadata.namo.chhanda` | `name` (`anuṣṭubh`, `triṣṭubh`, …), `syllables_per_pada`, `evidence` (the counts) |
| `metadata.namo.lemmas[]` | ≥ 5: `lemma` (DCS/SLP1), `deva`, `gloss`, `dcs_verses` (= `len(Corpus().search(lemma))`, measured), `sample` verse ids |
| `metadata.namo.speakers[]` | `verse_id`, `speaker_in_text` (whose words they are), `voiced_by` (who says them on screen) |
| `metadata.namo.world` | `set` (`hastinapur_hall` or `kurukshetra`), `era`, `bible_keys` checked |

## Process

### Step 1: Fix the Window

Take the verse window from the brief. If the brief names a Gita verse, map it to `M.6.(22+n).v` and confirm the GRETIL text matches the verse the brief quotes. No window, or a window outside the GRETIL file → refuse.

### Step 2: Pull the Sanskrit

From GRETIL take each verse's half-lines (`a` = padas a+b, `c` = padas c+d), main text only (no `*` star passages, no `@` appendix). Store IAST exactly as published. Convert to Devanagari mechanically. **Never type or "correct" Sanskrit by hand or by model.**

### Step 3: Verify Against DCS

For each verse, read the same verse from the DCS corpus. Normalise both (drop spaces, `।`, `॥`, punctuation) and compare. Equal → `dcs_match: true`. Different → record `dcs_text`, and stop with the difference listed: a text the two primary sources disagree on is not spoken until the owner decides.

### Step 4: Measure the Metre

Count syllables per half-line from IAST (one syllable per vowel nucleus: `a ā i ī u ū ṛ ṝ ḷ e ai o au`, `ai`/`au` count once). 16 + 16 = anuṣṭubh (8 per pada); 22 + 22 = triṣṭubh (11 per pada). Any other count: name the metre only if the counts prove it; otherwise record the counts and `name: "unidentified"` — never guess.

### Step 5: Measure the Words

Pick ≥ 5 lemmas that carry the verse (people, places, the verb of the question, objects that must appear on screen). For each, run `Corpus().search(lemma)` and record the verse count and 2–3 sample ids. For people and objects that will be drawn, run `namo_text.Text().describe(lemma)` and keep only descriptions with a verse id: if the text is silent about a look, the brief stays silent.

### Step 6: Place It

Confirm the set and era against `SHOW_BIBLE.world` and `.era` (late Vedic Kuru kingdom, c. 900 BCE; fire in every hall; not Mughal, not Rajput, not a temple town). Chariot banners only from `SHOW_BIBLE.banners` (Yudhishthira's lion is forbidden).

### Step 7: Who Speaks

For every verse record whose words they are in the text and who voices them on screen. Words of Arjuna, Krishna or Bhishma inside Sanjaya's report are voiced by `sanjaya` (he narrates the battlefield to the blind king).

### Step 8: Validate and Submit

Validate against the schema, then check the stage criteria yourself before handing over:

- [ ] Every spoken half-line has Devanagari + IAST, and every verse has a chhanda with syllable evidence and `dcs_match: true`
- [ ] ≥ 5 lemmas with measured DCS counts
- [ ] `world.set` and `world.era` match `SHOW_BIBLE`
- [ ] Every `data_points[].claim` carries a verse id

## Refuse When

- GRETIL or the DCS corpus cannot be read (network or missing `corpus/mahabharatam.txt`): the stage fails with the path or URL that failed. No fallback to memory — the handoff already records English lines "partly from memory" as a defect.
- The two sources disagree on a spoken verse.
- A requested detail (a look, a banner, an object) has no verse.

## Common Pitfalls

- **Model-written Sanskrit.** One wrong vowel is heard by every Sanskrit-literate viewer. The text comes from GRETIL, converted by code.
- **Vulgate numbering.** Popular Gita editions and the BORI edition can differ; match the text, not the number.
- **Counting tokens instead of verses.** State the unit: `dcs_verses` counts verses containing the lemma.
