# News slides and narrated video

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-11

Create an illustrated HTML presentation from a saved report or an independently collected index, then export a narrated MP4 when requested. Each story displays its headline and full narration, alongside its sources and available images. The saved deck also retains the editorial summary. [中文](zh-CN/news-slides.md)

## Choose the input

| Input | Selection and output |
| --- | --- |
| Saved report and matching index | Review current candidates, merge coverage of the same event while retaining references, and rank up to 50 by impact. |
| Index alone | Ask the host model to choose and order 50 item IDs by importance, then pass repeated `--item-id` options. Preparation without explicit IDs uses the CLI's source-rank fallback. |

Use `--max-news N` for another positive limit. Report finalization accepts `--slides-max-news N`; resuming a run preserves its previous limit unless explicitly changed. The review pool contains up to 15 eligible stories per source, ordered by original publication time after same-source canonical de-duplication. Missing images do not exclude a story; unknown publication dates are ineligible for today's stream.

```sh
signaltrail --data-dir DATA_DIR slides prepare --report REPORT.json --index INDEX.json
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language en --item-id ID1 --item-id ID2
```

Report mode follows the saved report language. When an index selection is bound to a report, a lead article that is the sole source of a featured event uses that event’s edited headline. The source details retain the publisher’s headline. Index mode uses `--language`, then the configured output language. The independent path creates a standalone presentation; the report path also updates its HTML projection.

## Write and render

Preparation extracts missing or incomplete article bodies and freezes bounded writing packets. Each packet includes the complete available source text, extraction status, writing instructions, and output schema. The default batch is five stories, with a 64,000-token estimated input target and 4,000-token output allowance. A longer single article expands the default input allowance; explicit `--max-input-tokens` is a hard limit. Bodies are kept complete.

Writing evidence omits local Markdown frontmatter and excludes Feed records consisting only of comment links, article links, or scores. If a selected event has only these records and no substantive body or description, preparation stops before creating writing packets and lists the event IDs, item IDs, and original/enriched index paths for evidence recovery or replacement. Saved access and rate-limit observations remain available. Substantive short descriptions remain usable.

Daily finalization saves these evidence gaps and the enriched index even when the first plan could not be created. Retrying the same report and source index reuses that evidence, including completed access attempts. `edition-status --require-complete` reports `evidence_required` and supplies a replacement command with the affected event IDs excluded.

Each author runs `slides input --packet PACKET.json` once to read the complete, compact `payload.model_input`. The command verifies the saved packet and emits its existing input losslessly, including full article bodies, the current narration style, output schema, and applicable video-title context. It also accepts older saved packets. Report-mode results contain `event_id`, `narration`, `video_tldr`, and permitted `perspectives`; index mode also writes the target-language title and summary. Chinese narration is 200–350 non-whitespace characters. Follow the embedded narration style and preserve factual qualifiers. Detailed writing and budget rules live in the [runtime reference](../references/news-slides.md).

```sh
signaltrail --data-dir DATA_DIR slides input --packet PACKET.json
signaltrail --data-dir DATA_DIR slides submit --packet PACKET.json --input DRAFT.json
signaltrail --data-dir DATA_DIR slides status --plan PLAN.json
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json
```

Use the exact plan and packet paths returned by preparation or recorded in `artifacts.slides`. Isolated workers can handle up to three packets concurrently. Save drafts as `batch-N-draft.json` beside their packets. For a directory of drafts, run `slides submit --plan PLAN.json --draft-dir DRAFT_DIR --check-only`, then repeat without `--check-only` to accept valid batches. Rendering requires every batch to be accepted.

Use `--reuse-plan OLD_PLAN.json` to reuse accepted stories whose writing inputs are unchanged. Report finalization supplies its previous plan automatically. Changed text, language, or analysis requires new writing; image changes can reuse narration. Preparation and status return `reused_count` and `pending_news_count`.

Every daily edition includes a rendered presentation. If finalization deferred delivery work, run its recorded `tail.command` and wait for it to exit before rendering. Check the finished edition with:

```sh
signaltrail --data-dir DATA_DIR edition-status --run RUN.json --require-complete
```

Completion requires `delivery_complete: true`, no pending steps, and rendered slides. The [runbook](../references/runbook.md) covers recovery.

## Images and report reading

Online rendering adds publisher images and captions from public article pages. Complete, untruncated article extraction can supply the same page images without another publisher-page request when the original, final, and slide source URLs match exactly apart from fragments. Missing evidence, changed URLs, and explicit refresh retain page fetching; image downloads and quality selection still run. Metrics distinguish `sources_fetched` from `source_pages_reused`. When a publisher supplies several sizes of one photo, SignalTrail tries the largest first and falls back to a smaller copy if the download fails or exceeds the configured budget. The gallery keeps the highest-resolution available copy per photo, including when rendering from previously saved images. It offers thumbnails, an enlarged view, original-size inspection, and an original-image link. Missing publisher captions stay empty.

Share images come from the page head, and article illustrations come from the selected article body. A successful page refresh drops older page candidates whose photo identity the new extraction cannot confirm. If page access fails, the existing index candidates remain available as a fallback.

Known subscription graphics are excluded from candidate selection. Articles that share one downloaded photo keep their own captions and publisher credits.

Responsive `srcset`, same-viewport `picture` format alternatives, fallback images and known publisher resize URLs share one photo group before downloading. A matching higher-resolution copy in the local cache also participates in selection. The selected file counts once toward the slide image budget; distinct encodings or sizes that can only be matched after downloading have already consumed download bytes. Existing files referenced by older reports remain subject to the normal retention policy.

BBC Feed thumbnails use the publisher's public resize route to try a 1920-pixel version, including when a small image is already cached. Stored dimensions come from the downloaded file. BBC path sizes and WordPress query sizes are grouped by original photo and crop; signatures and different crops remain distinct. The slide contents show publisher names beneath each title, and the report contents link directly to source groups.

Publisher-generated crops and thumbnails are grouped by their original asset identity. A single local article-body photo whose alternative text exactly matches its own source headline leads the gallery. The remaining photos retain their relative order and original captions. On phones, the headline and publisher appear above the gallery, followed by the narration. Compact controls leave more room for the first photo. To apply the selection to a saved deck, create a new revision with offline rendering.

```sh
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json --offline
```

Offline rendering reuses the saved deck and local images. Layout and image refreshes use no model calls. The local template follows the [MiMo site-02 design](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/), with serif headlines, editorial columns, and images in their original proportions.

Report HTML embeds the presentation and provides a separate open link. Printing restores the report summary, with links to each available analysis domain and the cross-perspective synthesis. After video export, the reader can switch between the presentation and video in the same frame; the desktop HTML copy is refreshed too. Versioned report JSON and Markdown remain the saved report records.

## Export video

When video is requested, start `slides prefetch-speech --plan PLAN.json --output FINAL.mp4 --follow-seconds 900` while slide authors work. It consumes accepted scripts as they appear and keeps one local synthesizer resident. Use the same output path and speech options for export, and await the prefetch process before starting `slides video`. The prefetch receipt separates generated pages, cache hits and pending work.

The model writes `video_tldr` from the full narration: target 60–100 Chinese characters, maximum 160 characters. Speech reads each story's title and short script. The first pending writing packet also produces an edition `video_title` from the selected headlines. Export uses explicit `--title`, then `video_title`, then the deck title.

```sh
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

The default engine is native Qwen3-TTS 1.7B Q8 with the bundled reference voice. Setup downloads the platform's programs, model, FFmpeg, and browser; subsequent exports reuse the cache. GPU synthesis is preferred after a synthesis probe, with CPU fallback. Select `--device auto|cpu|cuda|vulkan|metal` when needed. Windows ARM64 requires an explicit `--ffmpeg`; Linux needs browser system libraries and Chinese fonts.

Video captures the delivered slide HTML in a 1920 × 1080 viewport at 100% scale. Each frame uses the interactive presentation’s layout, including its full narration, source links, captions, and controls. Speech reads the title and short script at 1.08× speed. Measured speech duration controls page changes and image rotation. Matching speech segments, page audio, and rendered page clips are cached separately. Keep the output path stable to reuse the adjacent work directory. Export returns the video, timeline, diagnostics, actual device, and cache counters.

Repeated exports verify the ordered page audio and clips, timings, encoder and title settings, and the existing MP4 against a saved receipt. A match sets `video_cache_hit` and skips final audio concatenation and muxing. Cache verification time is reported separately. The export receipt records the SHA-256 of the submitted deck and the final MP4 for edition-level acceptance.

Exports sharing a page cache take an operating-system lock. An active export rejects another writer, and process exit releases ownership even after a forced stop. The lock file remains on disk. The exporter checks any legacy owner PID and migrates a stale legacy lock to a compatibility marker. Previous versions reject that marker, so use the updated exporter to retry or continue writing the same output.

Frame capture advances CSS animations to their final state. Each selected image has a 30-second loading budget. A timed-out image uses the existing unavailable-image layout and adds a `render_image` / `timed_out` diagnostic with its event and image number, allowing the remaining frames to finish.

When a Qwen log confirms that a segment reached the frame limit, synthesis splits that segment once at original punctuation or a word boundary. Continuous Chinese text can split between characters near its midpoint. Completed segments keep their cache, and the same model, device, voice and full text are used. A child segment reaching the limit stops export with its diagnostic. The voice manifest records the original segment, replacement parts and failed log in `frame_limit_recoveries`.

Video export prefetches one page of speech with a single worker while the main thread captures and encodes the current page in one browser session. Measured audio duration fixes each page's timing before frame capture. Completed page caches remain reusable after a failed export. `tts_seconds`, `render_seconds`, and `encode_seconds` record work performed by each stage; overlapping stages can run at the same time. `pipeline_seconds` measures elapsed time for speech, frame capture, and page encoding together, before final audio concatenation and MP4 assembly.

For a custom voice, complete [profile.example.json](../assets/tts/profile.example.json) with a short recording and exact transcript, then register and select it:

```sh
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4 --voice NAME
```

Registered recordings are copied into `video-runtime/voices/NAME/` with relative paths. `--reference-id ID` selects another reference in a profile. Omission uses `SIGNALTRAIL_VOICE`, then the registered default. The deck's language controls synthesis.

Review returns all eligible candidates; `--max-news` limits the final selection. `slides review --model-input` emits the same titles, evidence leads, source identities, publication times and access states in a compact column format, avoiding repeated field names, source names and URLs. Original URLs remain in the index under the retained item IDs. A source image hint helps reviewers retain relevant illustrated reports when merging coverage. Image download is checked separately.

## Limitations

Image availability and resolution depend on the publisher and download results; SVG paper figures are unsupported. Token estimates control packet size, while actual usage comes from the host adapter and stays `null` when unmetered. Structural validation checks the writing contract; factual review belongs to collection, selection, and authoring. See the [runtime reference](../references/news-slides.md) for network policy, pronunciation, audio processing, and cache details.

Cold GPU synthesis can produce different waveforms and durations across runs with a fixed seed. Each exported page follows its own measured audio duration; repeat exports reuse saved audio when the inputs match.

Video export discovers an existing `llama-tts-worker` under `DATA_DIR/video-runtime/qwen3/worker/`, beside a supplied native program, beside the selected model directory, or in the bound default data root. `SIGNALTRAIL_TTS_WORKER` explicitly selects a worker. The runtime probes the worker's own devices and keeps the model and reference voice loaded when its backend matches. Each segment retains its WAV, frame diagnostics and pronunciation checks; the worker closes after export.
`--model-dir` takes precedence over `SIGNALTRAIL_TTS_MODEL_DIR` and can name a cache to populate. Without either option, setup looks for the matching Q8 model and projector together in the current run's model cache, beside the explicitly supplied worker or native executable and its installation, and then in the bound default data root. Automatic discovery reads existing pairs in place. When it finds none, it downloads into the current run's model cache.
`video-setup` and video export report `execution_mode`, `worker_path` or `tts_worker_executable`, and the selection reason. In `auto`, an available resident GPU backend takes priority; Windows prefers resident Vulkan before resident CUDA. Explicit device selection takes precedence. If no matching worker exists, `execution_mode: oneshot` uses the original native CLI and reports that each uncached segment loads the model. Reuse a compatible worker for an isolated data root; no worker build is required to continue.

Before narration, run `slides review --report REPORT.json --index INDEX.json`. Review today's candidates and replacements, then pass a decision JSON to `slides prepare --review REVIEW.json`. Use `selected_event_ids`, `exclude_event_ids` and `merge_groups` (leader first); merged events retain all source references. Eligibility uses the edition date in Asia/Shanghai and original publication dates, including original-page dates for discovery sources. Unknown dates, older stories and ranking/collection timestamps do not qualify. Review substantive changes and semantic event identity before writing. Deliver fewer than 50 when the current distinct pool is short; keep the actual count visible.

After preparation enriches article evidence and before dispatching any narration author, review the actual evidence for every final story (up to 50) and any replacements. Read one compact projection of existing `plan.payload.news[].evidence`: source headline, opening paragraph, body length, access status and available Feed text. Read full text only where that projection leaves a concrete question. A title alone, author biography, photo caption or mismatched article is insufficient article evidence. Substantive Feed evidence can support a narrower script when its partial provenance is stated; replace unsupported stories from the reviewed reserves. Complete this final evidence review and recheck original publication dates against the edition day and frozen cutoff before dispatch. Keep selection, replacement and date review in the same editorial pass.

Use `finalize-edition --slides-review REVIEW.json --slides-reuse-plan OLD_PLAN.json` to reuse matching accepted narration from an independent plan when binding slides to a report revision. The explicit plan takes precedence over current and previous-report plans; current review, date eligibility and writing-input identity still determine reuse.

When the supplied plan is already complete and its rendered HTML matches the saved report's slides, finalization can restore the manifest association directly. The report, index, and review must match the existing plan. This recovery leaves the delivered files in place.

New CLI preparation and report finalization stop at `review_required` before creating narration packets. Save the model decision, then use `slides prepare --review REVIEW.json` or `finalize-edition --slides-review REVIEW.json`. Edition status exposes `slides_review` as pending. Existing historical plans remain resumable. Precise timestamps after the frozen edition cutoff are excluded; date-only evidence for the same day keeps its original precision.

Candidate review ranks merged current events by affected people, regions and industries, severity across policy/economics/technology/security, persistence or irreversibility, and evidence strength. `selected_event_ids` preserves the final editorial order through the deck; popularity and source order do not replace impact assessment. Optional concise ranking reasons may accompany the decision.

An empty current-day pool returns `no_items` with a concrete choice to collect additional current sources or deliver the report alone; it does not request an empty review.
