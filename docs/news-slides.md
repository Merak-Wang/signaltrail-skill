# News slides

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-23

News slides are a standalone, animated HTML presentation derived from a saved daily report and its index. Each selected story occupies one navigable slide. It shows the indexed source, summary, available story images, and their extracted captions alongside model-written narration. Only stories published on `report.date` are eligible. The authoritative date is `index.items[].published_at`, converted using `report.timezone`, then `index.timezone`, then `Asia/Shanghai`; missing or invalid publication times are excluded. Feed update timestamps are not publication dates. Discovery sources such as Hacker News and Lobsters use the platform submission date, so an older original article can qualify when shared that day. Content extraction preserves that submission date and records the original-page date separately in `metadata.content_source.published_at`. Direct publisher sources use the article publication date. Explicit `--item-id` selections obey the same rule. Aggregated events that mix publication dates are skipped; eligible individual briefs can still be selected, so old-source summaries are not retained after merely dropping their citations. This filter applies only to slides and does not change the main report. When a deck exists, the report HTML embeds it in place of the on-screen executive summary and keeps an **Open visual edition** link for opening the deck separately. Printing hides the embedded presentation and restores the summary. The daily report's JSON and Markdown remain unchanged and authoritative; later HTML rebuilds retain the presentation while its projection exists.

The visual reference is [Frontend Design example site 02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/): warm off-white (`#f3f4ef`), deep green ink (`#1c2422`), restrained terracotta accents, oversized serif headlines, asymmetrical editorial columns, fine rules and side numbering. News images retain their original proportions, and transitions respect reduced-motion preferences. The template is local and deterministic, so styling adds no model calls or generation cost.

Online page requests share one HTTPX connection pool. A per-domain round-robin scheduler fills newly free global worker slots while respecting global and per-domain limits; image downloads also use bounded concurrency.

Story imagery combines cover and article-body candidates from the index with images and original captions extracted from each selected story's public article page during the default online render. Explicit `srcset` and URL size/DPR declarations guide selection of higher-resolution candidates; actual resolution depends on what the publisher exposes and downloads successfully. Images inside in-article game, promotion, subscription, or same-page recommendation containers are not treated as article imagery, and candidates that resolve to identical content are shown once. Candidates are deduplicated by image identity; the renderer does not impose a six-image cap. Downloads follow configured media budgets. A failed page fetch or image download leaves the existing indexed candidates available. This refresh only updates slide imagery; it does not change saved body evidence or access status. The gallery provides thumbnails, a larger view, 100% original-size inspection, and a direct link to the original image. Publisher captions remain attached to their images; missing captions stay empty and are never replaced with alt text. The current and next story images load eagerly; images in distant stories stay lazy until needed. Shared local images are encoded once per render.

## Default daily flow: prepare, write, render

Finalizing a daily report automatically prepares a slide plan and bounded writing packets from
the saved report and matching index. The run manifest records them at
`artifacts.slides.plan_path` and `artifacts.slides.packet_paths`; no model call is made during
preparation. Packets are independent: write up to three concurrently, wait for the full wave, then
start the next wave. SignalTrail's Hermes integration uses `delegate_task(background=False)` to wait
for each wave and caps `max_concurrent_children` at three. Submit each result after its worker returns. If finalization used
`--defer-tail`, run the manifest's exact `tail.command` in the background while slide writing
continues, keep its process handle and exit status, and wait for it to exit before rendering; both
the tail and slide render can update report projections. If preparation fails, the report remains
saved and `artifacts.slides.error` records the reason; retry preparation from the saved report and
index. Calling `slides prepare` directly remains the recovery path.

## Prepare, write, render

Collection also reads an image's explicit full-size link when present. Known CDN size variants are merged without inventing URLs, and a higher-resolution remote image never inherits a thumbnail's local cache file. Captions stay within the image container; quotation attributions elsewhere in the article are excluded. Opening a larger image from the embedded deck expands its viewport above the report toolbar, then restores the container on close.

Prepare a slide plan from a saved report and its matching index:

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
```

By default, candidates are the report's selected items plus report briefs with importance at or above 70, deduplicated by brief. There is no issue-wide story limit. Repeated `--item-id ID` options override the default selection and each ID must belong to the report; they do not admit arbitrary index items. Each prepared packet assigns a bounded group of stories to one writing call; the default batch size is four. The packet carries the style instructions, output schema, allowed analysis perspectives, and the assigned report evidence.

Read only `packet.payload.model_input` to write the batch; its schema is at `payload.model_input.output_schema` and cost reserve is separate at `payload.budget`. Submit the resulting JSON with `signaltrail slides submit --packet PACKET.json --input DRAFT.json`. Emit every assigned event exactly once as `{event_id, narration, perspectives}`. `perspectives` may be empty and may contain only relevant `geopolitics`, `markets`, or `ai_technology` domains present in that event's analysis. Do not repeat titles, summaries, sources, image URLs, or captions in the model output; the renderer attaches these program fields. A successful submission is reused. Invalid drafts do not trigger an automatic repair. Keep each worker on one packet and do not exceed three concurrent packets; finish one wave before dispatching the next.

The packet contains a copy of the [narration style](../templates/news-slide-style/SKILL.md), so a worker can follow its voice without loading extra editorial material. Chinese narration is validated at 200–350 non-whitespace characters, including punctuation; English narration has no equivalent length check. Read the [budget and packet reference](../references/news-slides.md) when changing batch size or token gates.

Render only after all planned batches have been submitted:

```text
signaltrail slides render --plan PLAN.json
signaltrail slides render --plan PLAN.json --offline
signaltrail slides status --plan PLAN.json
```

Rendering produces a navigable HTML deck, a structured deck JSON, and Markdown. Story titles, summaries, and source references come from the report; the index supplies source names, publication times, and cover plus article-body image candidates. By default, render reads the selected stories' public article pages to supplement image candidates and publisher captions. It follows explicit `srcset` entries and declared URL width/DPR when choosing among variants, then caches successful downloads within configured media budgets. Page or image failures preserve the existing candidates. This image refresh does not alter stored article text, its evidence, or its access status, and makes no model call. Use `--offline` to rebuild from the existing deck and image files without fetching pages or downloading images, for layout-only changes. Candidates are deduplicated by image identity; resolution is limited by publisher-provided variants and download success, and there is no fixed per-story image limit. The gallery supports thumbnail selection, a larger view, 100% original-size inspection, and opening the original image URL. If any writing batch is pending or missing, render stops; it does not silently omit assigned stories. Status reports completed and pending batches. HTML styling and transitions are deterministic.

`slides prepare` reads only the supplied saved report and index; it does not fetch webpages or call a model. It applies the publication-date rule above using only `index.items[].published_at`; it never substitutes collection or index-update time. If you need richer body evidence before making or updating an index, use the supported `extract-content` command on selected items and then prepare from its returned enriched index. This extracts article text into a new index revision. Online slide rendering separately supplements image candidates from the selected public article pages. When only image metadata changes, accepted narration can be reused and no new model call is needed.

## Batch cost gates

Use `--batch-size`, `--max-input-tokens`, and `--max-output-tokens` on `slides prepare` to set per-batch limits. Defaults are four stories, 12,000 estimated input tokens, and 4,000 estimated output tokens. Output reserves 700 estimated tokens per story. Input estimate is serialized UTF-8 bytes divided by two, plus 512 tokens of reserve. These are coarse size gates, not tokenizer counts, dollar quotes, or guarantees of host usage. Actual usage remains unknown (`null`) unless the host exposes it. All selected stories remain in the plan and are handled through as many batches as needed.

The host is responsible for making the writing call. SignalTrail prepares bounded packets and accepts results; it does not automatically invoke a model, retry a draft, or incur a separate review call.
