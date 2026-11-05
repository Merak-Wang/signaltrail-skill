# News slides and narrated video

**Status:** Verified · **Owner:** Repository maintainers · **Last verified:** 2026-11-02

Create an illustrated HTML presentation from a saved report or an independently collected index, then export a narrated MP4 when requested. Each story has its own page, sources, summary, available images, and model-written narration. [中文](zh-CN/news-slides.md)

## Choose the input

| Input | Selection and output |
| --- | --- |
| Saved report and matching index | Merge duplicate original stories, retain their references, and rank the report's events and briefs by model-authored importance. The default is 50 stories. |
| Index alone | Ask the host model to choose and order 50 item IDs by importance, then pass repeated `--item-id` options. Preparation without explicit IDs uses the CLI's source-rank fallback. |

Use `--max-news N` for another positive limit. Report finalization accepts `--slides-max-news N`; resuming a run preserves its previous limit unless explicitly changed. There is no per-source quota. Missing images and unknown publication dates do not exclude a story.

```sh
signaltrail --data-dir DATA_DIR slides prepare --report REPORT.json --index INDEX.json
signaltrail --data-dir DATA_DIR slides prepare --index INDEX.json --language en --item-id ID1 --item-id ID2
```

Report mode follows the saved report language. Index mode uses `--language`, then the configured output language. The independent path creates a standalone presentation; the report path also updates its HTML projection.

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

Online rendering adds publisher images and captions from public article pages. When a publisher supplies several sizes of one photo, SignalTrail tries the largest first and falls back to a smaller copy if the download fails or exceeds the configured budget. The gallery keeps the highest-resolution available copy per photo, including when rendering from previously saved images. It offers thumbnails, an enlarged view, original-size inspection, and an original-image link. Missing publisher captions stay empty.

Publisher-generated crops and thumbnails are grouped by their original asset identity. Distinct photographs retain their order and captions. To apply the selection to a saved deck, create a new revision with offline rendering.

```sh
signaltrail --data-dir DATA_DIR slides render --plan PLAN.json --offline
```

Offline rendering reuses the saved deck and local images. Layout and image refreshes use no model calls. The local template follows the [MiMo site-02 design](https://mimo.xiaomi.com/mimo-v2-6/assets/frontend/site-02/), with serif headlines, editorial columns, and images in their original proportions.

Report HTML embeds the presentation and provides a separate open link. Printing restores the report summary. After video export, the reader can switch between the presentation and video in the same frame; the desktop HTML copy is refreshed too. Versioned report JSON and Markdown remain the saved report records.

## Export video

The model writes `video_tldr` from the full narration: target 60–100 Chinese characters, maximum 160 characters. Speech reads each story's title and short script. The first pending writing packet also produces an edition `video_title` from the selected headlines. Export uses explicit `--title`, then `video_title`, then the deck title.

```sh
signaltrail --data-dir DATA_DIR slides video-setup
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4
```

The default engine is native Qwen3-TTS 1.7B Q8 with the bundled reference voice. Setup downloads the platform's programs, model, FFmpeg, and browser; subsequent exports reuse the cache. GPU synthesis is preferred after a synthesis probe, with CPU fallback. Select `--device auto|cpu|cuda|vulkan|metal` when needed. Windows ARM64 requires an explicit `--ffmpeg`; Linux needs browser system libraries and Chinese fonts.

Video captures the presentation's existing text, images, columns, and page order at 140% whole-page zoom. Measured speech duration controls page changes and image rotation. Speech plays at 1.08× speed. Matching speech segments, page audio, and rendered page clips are cached. Keep the output path stable to reuse the adjacent work directory. Export returns the video, timeline, diagnostics, actual device, and cache counters.

Frame capture advances CSS animations to their final state. Each selected image has a 30-second loading budget. A timed-out image uses the existing unavailable-image layout and adds a `render_image` / `timed_out` diagnostic with its event and image number, allowing the remaining frames to finish.

Video export prefetches one page of speech with a single worker while the main thread captures and encodes the current page in one browser session. Measured audio duration fixes each page's timing before frame capture. Completed page caches remain reusable after a failed export. `tts_seconds`, `render_seconds`, and `encode_seconds` record work performed by each stage; overlapping stages can run at the same time. `pipeline_seconds` measures elapsed time for speech, frame capture, and page encoding together, before final audio concatenation and MP4 assembly.

For a custom voice, complete [profile.example.json](../assets/tts/profile.example.json) with a short recording and exact transcript, then register and select it:

```sh
signaltrail --data-dir DATA_DIR slides voice-setup --profile PROFILE.json --default
signaltrail --data-dir DATA_DIR slides video --deck DECK.json --output VIDEO.mp4 --voice NAME
```

Registered recordings are copied into `video-runtime/voices/NAME/` with relative paths. `--reference-id ID` selects another reference in a profile. Omission uses `SIGNALTRAIL_VOICE`, then the registered default. The deck's language controls synthesis.

## Limitations

Image availability and resolution depend on the publisher and download results; SVG paper figures are unsupported. Token estimates control packet size, while actual usage comes from the host adapter and stays `null` when unmetered. Structural validation checks the writing contract; factual review belongs to collection, selection, and authoring. See the [runtime reference](../references/news-slides.md) for network policy, pronunciation, audio processing, and cache details.

Cold GPU synthesis can produce different waveforms and durations across runs with a fixed seed. Each exported page follows its own measured audio duration; repeat exports reuse saved audio when the inputs match.
