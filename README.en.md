# SignalTrail

[简体中文](README.md) | [English](README.en.md)

SignalTrail collects public news locally, uses your agent to write Chinese or English daily reports, and turns selected stories into illustrated presentations and narrated videos. Use it to catch up on the day, follow original sources, and share a readable briefing.

- **Daily reports:** News summaries and analysis with original source links, saved as HTML, PDF, Markdown, and JSON.
- **Slides and video:** Select the 50 most important stories by default and optionally export a 1080p video with local Qwen3-TTS speech. Presentations can also be created directly from a collected index.
- **Collection monitor:** Browse news, story clusters, and source health, and extend coverage through source configuration.

## Latest example

This Chinese daily report was generated on November 2, 2026. Its presentation and video cover 50 stories; the video runs for 16 minutes 11 seconds. Click the preview to download it:

[![November 2, 2026 news video preview](assets/readme/daily-video-preview.png)](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-11-02-daily-r1-video.mp4)

[Download narrated MP4](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-11-02-daily-r1-video.mp4) · [Download report and presentation ZIP](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-11-02-daily-r1.zip) · [Download standalone slides HTML](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-11-02-daily-r1-slides.html)

Extract the ZIP and open `2026-11-02-daily-r1.html`. Save the MP4 in the same directory to switch between slides and video in the report.

![November 2, 2026 report reader](assets/readme/daily-report-preview.png)

## Quick start

You need Python 3.11+, Git, and a model-configured agent that can read and write files and run commands.

```sh
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
python -m pip install -e .
python -m playwright install chromium
signaltrail --help
```

Load the repository's root [SKILL.md](SKILL.md) in your agent, then ask:

```text
Use SignalTrail to generate today's English daily report with illustrated
slides and a narrated video. Save the HTML, PDF, and video locally.
```

The agent selects and writes the stories; the CLI collects, renders, and archives them. For a standalone presentation, ask:

```text
Collect today's news, select the 50 most important stories, and create
an English illustrated presentation and narrated video.
```

The first video setup downloads tools and models; later exports reuse local caches. See [Usage](docs/usage.md) for installation, data paths, and recovery.

## Configuration and documentation

Output defaults to Chinese. Request English or set `output.language: en`. Edit [sources.yaml](configs/sources.yaml) for core sources and [discovery-sources.yaml](configs/discovery-sources.yaml) for extension sources. Enabled entries in both bundles enter existing report sections, retaining all eligible current-day articles in each source's original Top order.

| Guide | Covers |
| --- | --- |
| [Usage](docs/usage.md) | Installation, language, data paths, host usage, and recovery |
| [Slides and video](docs/news-slides.md) | Report and index-only inputs, rendering, speech, and custom voices |
| [Collection extensions](docs/platform.md) | Local monitor, RSSHub, Crawl4AI, and event archives |
| [Development](docs/development.md) · [Architecture](ARCHITECTURE.md) | Code structure, maintenance, and checks |
| [Documentation index](docs/README.md) · [Changelog](CHANGELOG.md) | Other guides and release history |

## License

[MIT License](LICENSE). Attribution for the optional Crawl4AI extraction integration:

This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).
