# News slides

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-23

News slides are a standalone, animated HTML presentation derived from a saved daily report and its index. Each selected story occupies one navigable slide. It shows the indexed source, summary, available story images, and their extracted captions alongside model-written narration. When a deck exists, the report HTML embeds it in place of the on-screen executive summary and keeps an **Open visual edition** link for opening the deck separately. Printing hides the embedded presentation and restores the summary. The daily report's JSON and Markdown remain unchanged and authoritative; later HTML rebuilds retain the presentation while its projection exists.

The visual reference is [Frontend Design example site 02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/): warm off-white (`#f3f4ef`), deep green ink (`#1c2422`), restrained terracotta accents, oversized serif headlines, asymmetrical editorial columns, fine rules and side numbering. News images retain their original proportions, and transitions respect reduced-motion preferences. The template is local and deterministic, so styling adds no model calls or generation cost.

Story imagery combines cover and article-body candidates from the index. Candidates are deduplicated by image identity, preferring the higher-resolution variant; the renderer does not impose a six-image cap. The gallery provides thumbnails, a larger view, 100% original-size inspection, and a direct link to the original image. Extracted captions remain attached to their images. The current and next story images load eagerly; images in distant stories stay lazy until needed. Shared local images are encoded once per render.

## Default daily flow: prepare, write, render

Finalizing a daily report automatically prepares a slide plan and bounded writing packets from
the saved report and matching index. The run manifest records them at
`artifacts.slides.plan_path` and `artifacts.slides.packet_paths`; no model call is made during
preparation. The writing host completes every packet, submits the result, then renders the plan
before treating the default edition as finished. If preparation fails, the report remains saved
and `artifacts.slides.error` records the reason; retry preparation from the saved report and index.
Calling `slides prepare` directly remains the recovery path.

## Prepare, write, render

Collection also reads an image's explicit full-size link when present. Known CDN size variants are merged without inventing URLs, and a higher-resolution remote image never inherits a thumbnail's local cache file. Captions stay within the image container; quotation attributions elsewhere in the article are excluded. Opening a larger image from the embedded deck expands its viewport above the report toolbar, then restores the container on close.

Prepare a slide plan from a saved report and its matching index:

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
```

By default, candidates are the report's selected items plus report briefs with importance at or above 70, deduplicated by brief. There is no issue-wide story limit. Repeated `--item-id ID` options override the default selection and each ID must belong to the report; they do not admit arbitrary index items. Each prepared packet assigns a bounded group of stories to one writing call; the default batch size is four. The packet carries the style instructions, output schema, allowed analysis perspectives, and the assigned report evidence.

Read only `packet.payload.model_input` to write the batch; its schema is at `payload.model_input.output_schema` and cost reserve is separate at `payload.budget`. Submit the resulting JSON with `signaltrail slides submit --packet PACKET.json --input DRAFT.json`. Emit every assigned event exactly once as `{event_id, narration, perspectives}`. `perspectives` may be empty and may contain only relevant `geopolitics`, `markets`, or `ai_technology` domains present in that event's analysis. Do not repeat titles, summaries, sources, image URLs, or captions in the model output; the renderer attaches these program fields. A successful submission is reused. Invalid drafts do not trigger an automatic repair.

The packet contains a copy of the [narration style](../templates/news-slide-style/SKILL.md), so a worker can follow its voice without loading extra editorial material. Chinese narration is validated at 200–350 non-whitespace characters, including punctuation; English narration has no equivalent length check. Read the [budget and packet reference](../references/news-slides.md) when changing batch size or token gates.

Render only after all planned batches have been submitted:

```text
signaltrail slides render --plan PLAN.json
signaltrail slides status --plan PLAN.json
```

Rendering produces a navigable HTML deck, a structured deck JSON, and Markdown. Story titles, summaries, and source references come from the report; the index supplies source names, publication times, and cover plus article-body image candidates with extracted captions. Candidate URLs are deduplicated while preferring high-resolution images, with no fixed per-story image limit. The gallery supports thumbnail selection, a larger view, 100% original-size inspection, and opening the original image URL. Remote images require a network connection; failed loads show a placeholder. If any batch is pending or missing, render stops; it does not silently omit assigned stories. Status reports completed and pending batches. HTML styling and transitions are deterministic and make no model call.

`slides prepare` reads only the supplied saved report and index; it does not fetch webpages or call a model. If you need richer body evidence before making or updating an index, use the supported `extract-content` command on selected items and then prepare from its returned enriched index. This extracts article text into a new index revision; it is not a dedicated image-download command, so slides use only image candidates already recorded in the index. When only image metadata changes, accepted narration can be reused and no new model call is needed.

## Batch cost gates

Use `--batch-size`, `--max-input-tokens`, and `--max-output-tokens` on `slides prepare` to set per-batch limits. Defaults are four stories, 12,000 estimated input tokens, and 4,000 estimated output tokens. Output reserves 700 estimated tokens per story. Input estimate is serialized UTF-8 bytes divided by two, plus 512 tokens of reserve. These are coarse size gates, not tokenizer counts, dollar quotes, or guarantees of host usage. Actual usage remains unknown (`null`) unless the host exposes it. All selected stories remain in the plan and are handled through as many batches as needed.

The host is responsible for making the writing call. SignalTrail prepares bounded packets and accepts results; it does not automatically invoke a model, retry a draft, or incur a separate review call.
