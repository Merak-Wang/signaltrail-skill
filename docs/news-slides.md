# News slides

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-09-23

News slides are a standalone, animated HTML presentation derived from a saved daily report and its matching index. Each selected story occupies one navigable slide with source, summary, available images, captions, and model-written narration. The candidate pool is the whole saved report: all selected events and briefs, regardless of publication date; slides do not add items directly from the index. Duplicate original stories are merged with all source references retained, then sorted by importance descending. The default is the first 50 stories; `slides prepare --max-news N` sets another positive limit, and `finalize-edition --slides-max-news N` configures the default edition workflow. There is no per-source quota. A new edition defaults to 50; resuming an existing run without an explicit limit preserves its saved choice, while an explicit change prepares a new plan. Unknown publication dates stay unknown and are not replaced with discovery, collection, or index-update time. Missing images do not exclude stories. This projection does not change the report. When a deck exists, the report HTML embeds it in place of the on-screen executive summary and keeps an **Open visual edition** link for opening the deck separately. Printing hides the embedded presentation and restores the summary. The daily report's JSON and Markdown remain unchanged and authoritative; later HTML rebuilds retain the presentation while its projection exists.

The visual reference is [Frontend Design example site 02](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/): warm off-white (`#f3f4ef`), deep green ink (`#1c2422`), restrained terracotta accents, oversized serif headlines, asymmetrical editorial columns, fine rules and side numbering. News images retain their original proportions, and transitions respect reduced-motion preferences. The template is local and deterministic, so styling adds no model calls or generation cost.

Online page requests share one HTTPX connection pool. A per-domain round-robin scheduler fills newly free global worker slots while respecting global and per-domain limits; image downloads also use bounded concurrency.

Story imagery combines cover and article-body candidates from the index with images and original captions extracted from each selected story's public article page during the default online render. For arXiv abstract pages, rendering follows only the explicitly linked HTML full text for the same paper to find supported body images; SVG figures remain unsupported. Explicit `srcset` and URL size/DPR declarations guide selection of higher-resolution candidates; actual resolution depends on what the publisher exposes and downloads successfully. Images inside in-article game, promotion, subscription, or same-page recommendation containers are not treated as article imagery, and candidates that resolve to identical content are shown once. Candidates are deduplicated by image identity; the renderer does not impose a six-image cap. Downloads follow configured media budgets. A failed page fetch or image download leaves the existing indexed candidates available. This refresh only updates slide imagery; it does not change saved body evidence or access status. The gallery provides thumbnails, a larger view, 100% original-size inspection, and a direct link to the original image. Publisher captions remain attached to their images; missing captions stay empty and are never replaced with alt text. The current and next story images load eagerly; images in distant stories stay lazy until needed. Shared local images are encoded once per render.

## Default daily flow: prepare, write, render

Finalizing a daily report automatically prepares a slide plan and bounded writing packets from
the saved report and matching index. Every default daily edition requires a rendered slide deck, in metered and unmetered runs. “Report saved” means the report artifacts are available; “edition delivery complete” requires all slide batches accepted, rendering finished, the tail exited, and the completion gate passed. A saved report and HTML may be handed off while the rest is pending. The run manifest records them at
`artifacts.slides.plan_path` and `artifacts.slides.packet_paths`; no model call is made during
preparation. Packets are independent: write up to three concurrently, wait for the full wave, then
start the next wave. SignalTrail's Hermes integration uses `delegate_task(background=False)` to wait
for each wave and caps `max_concurrent_children` at three. Submit each result after its worker returns using the manifest paths. Reuse accepted results and write a uniquely named draft JSON beside each packet. If finalization used
`--defer-tail`, run the manifest's exact `tail.command` in the background while slide writing
continues, keep its process handle and exit status, and wait for it to exit before rendering; both
the tail and slide render can update report projections. If preparation fails, the report remains
saved and `artifacts.slides.error` records the reason. To register a failed or missing preparation
in the run manifest, retry `signaltrail --data-dir DATA_DIR finalize-edition --run RUN.json --report
SAVED_REPORT.json --defer-tail`; standalone `slides prepare` remains available for independent use.
Then check `slides status --plan PLAN.json`, render only after all batches are accepted and tail exits,
and run `signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete`; require
`delivery_complete: true`, empty `pending_steps`, and `slides.status: rendered`. This dynamic command
is authoritative; run status and saved slide snapshots may precede rendering. Disclose every pending
step if the gate is false.

## Prepare, write, render

Collection also reads an image's explicit full-size link when present. Known CDN size variants are merged without inventing URLs, and a higher-resolution remote image never inherits a thumbnail's local cache file. Captions stay within the image container; quotation attributions elsewhere in the article are excluded. Opening a larger image from the embedded deck expands its viewport above the report toolbar, then restores the container on close.

Prepare a slide plan from a saved report and its matching index:

```text
signaltrail slides prepare --report REPORT.json --index INDEX.json
```

By default, candidates are the entire saved report's selected events and briefs. SignalTrail merges duplicate original stories, keeps all source references, sorts by importance descending, and prepares the first 50. Use `slides prepare --max-news N` for another positive limit, or `finalize-edition --slides-max-news N` for the edition workflow. The limit is issue-wide; it does not reserve a place for each source. When resuming, omission of `--slides-max-news` reuses the saved limit; an explicit change prepares a new plan. Items with unknown or older publication dates remain eligible because the report is the scope. Unknown dates remain unknown and are never filled from discovery or collection timestamps. Missing images do not exclude a story. Each packet assigns a bounded group of stories to one writing call; the default batch size is four. The packet carries the style instructions, output schema, allowed analysis perspectives, and assigned report evidence.

Read only `packet.payload.model_input` to write the batch; its schema is at `payload.model_input.output_schema` and cost reserve is separate at `payload.budget`. Submit the resulting JSON with `signaltrail slides submit --packet PACKET.json --input DRAFT.json`. Emit every assigned event exactly once as `{event_id, narration, perspectives}`. `perspectives` may be empty and may contain only relevant `geopolitics`, `markets`, or `ai_technology` domains present in that event's analysis. Do not repeat titles, summaries, sources, image URLs, or captions in the model output; the renderer attaches these program fields. A successful submission is reused. Invalid drafts do not trigger an automatic repair. Keep each worker on one packet and do not exceed three concurrent packets; finish one wave before dispatching the next.

The packet contains a copy of the [narration style](../templates/news-slide-style/SKILL.md), so a worker can follow its voice without loading extra editorial material. Chinese narration is validated at 200–350 non-whitespace characters, including punctuation; English narration has no equivalent length check. Read the [budget and packet reference](../references/news-slides.md) when changing batch size or token gates.

Use the exact plan and packet paths recorded in `artifacts.slides.plan_path` and `artifacts.slides.packet_paths[]`; do not infer them from revision names. Save each draft beside its packet as `batch-N-draft.json`, using that packet’s batch number. Run these commands with the same data root. Render only after all planned batches have been submitted and the tail has exited:

```text
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

Rendering produces a navigable HTML deck, a structured deck JSON, and Markdown. Story titles, summaries, and source references come from the report; the index supplies source names, publication times, and cover plus article-body image candidates. By default, render reads the selected stories' public article pages to supplement image candidates and publisher captions. It follows explicit `srcset` entries and declared URL width/DPR when choosing among variants, then caches successful downloads within configured media budgets. Page or image failures preserve the existing candidates. This image refresh does not alter stored article text, its evidence, or its access status, and makes no model call. Use `--offline` to rebuild from the existing deck and image files without fetching pages or downloading images, for layout-only changes. Candidates are deduplicated by image identity; resolution is limited by publisher-provided variants and download success, and there is no fixed per-story image limit. The gallery supports thumbnail selection, a larger view, 100% original-size inspection, and opening the original image URL. If any writing batch is pending or missing, render stops; it does not silently omit assigned stories. Status reports completed and pending batches. HTML styling and transitions are deterministic.

`slides prepare` reads only the supplied saved report and index; it does not fetch webpages or call a model. It uses the report as the candidate scope and reads `index.items[].published_at` only as source metadata; publication dates do not filter report candidates, and missing dates remain unknown. If you need richer body evidence before making or updating an index, use the supported `extract-content` command on selected items and then prepare from its returned enriched index. This extracts article text into a new index revision. Online slide rendering separately supplements image candidates from the selected public article pages. When only image metadata changes, accepted narration can be reused and no new model call is needed.

## Batch cost gates

Use `--max-news` to set the issue-wide story count, and `--batch-size`, `--max-input-tokens`, and `--max-output-tokens` for per-batch limits. Defaults are 50 stories, four stories per batch, 12,000 estimated input tokens, and 4,000 estimated output tokens. Output reserves 700 estimated tokens per story. Input estimate is serialized UTF-8 bytes divided by two, plus 512 tokens of reserve. These are coarse size gates, not tokenizer counts, dollar quotes, or guarantees of host usage. Actual usage remains unknown (`null`) unless the host exposes it. Selected stories are handled through as many batches as needed.

The host is responsible for making the writing call. SignalTrail prepares bounded packets and accepts results; it does not automatically invoke a model, retry a draft, or incur a separate review call.
