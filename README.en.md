# SignalTrail

[简体中文](README.md) | [English](README.en.md)

SignalTrail collects news from configured public sources and produces Chinese or English
morning and evening reports with links to the originals. Reports stay on your machine:
read them as HTML, share a PDF, or optionally sync to Notion.

The project combines a Python CLI with an agent [skill](SKILL.md). Python collects,
deduplicates, validates, and archives evidence; an agent writes the summaries and analysis.
Hermes has install scripts and usage metering. Other agents can use the same workflow
if they can run local commands and read and write JSON files.

[Quick start](#quick-start) · [Usage](docs/usage.md) ·
[Contributing](docs/development.md) · [Documentation](docs/README.md)

![Morning report preview](assets/readme/morning-report-preview.png)

The updated reader has a three-column masthead, white pages, black text, and red rules.
News runs continuously in source order, with each source heading identifying its section.
The floating directory opens, collapses, and follows the reading position. Original headlines,
translations, timestamps, images, and summary layouts remain intact.

## Example report

A report contains news summaries grouped by source, selected events, and analysis from
geopolitics, AI / technology, and markets. A synthesis connects the three perspectives;
an independent evaluation records scores and evidence gaps. Each item retains its original
headline, URL, and time; the original report retains access status and evidence limitations.

[Download the example HTML](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-08-25-morning-r1.html)
and open it locally. This historical example has 424 summaries, eight selected events,
and a score of 37/45. It has output from 30 of 32 sources and took about 66 minutes,
exceeding the one-hour budget. Some evidence contains only headlines and summaries;
public image URLs need an internet connection. See the [example notes](https://github.com/Merak-Wang/signaltrail-skill/blob/main/examples/README.en.md).

<details>
<summary>Analysis, evaluation, and mobile screenshots</summary>

![Cross-perspective synthesis](assets/readme/analysis-synthesis-preview.png)
![Independent evaluation](assets/readme/quality-evaluation-preview.png)
<img src="assets/readme/mobile-report-preview.png" width="390" alt="Mobile report">

</details>

## Quick start

You need Git, Python 3.11+, and an agent with a configured model.

```sh
git clone https://github.com/Merak-Wang/signaltrail-skill.git
cd signaltrail-skill
python -m pip install -e .
signaltrail --help
```

Load the root `SKILL.md` in your agent, then ask:

```text
Use SignalTrail to create today's English morning report as local HTML and PDF.
```

`signaltrail` and the existing `daily-intel` command share the same entry point.
The CLI runs the deterministic steps; the agent must author and submit the content.
Running `run-edition` alone stops at the authoring handoff.

Hermes users can run an installer from the repository directory:

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

```sh
# macOS / Linux
bash ./scripts/install.sh
```

The scripts install the Python package and synchronize the skill. See [Usage](docs/usage.md)
for browser dependencies, data directories, output language, and metered runs.

## Local monitor

Monitor refresh, deduplication, and clustering make no model calls. Browse news, source
health, and pending verification pages on your machine:

```sh
signaltrail refresh-monitor
signaltrail serve --open --refresh-minutes 30
```

The server listens on `127.0.0.1` by default and stops refreshing when the process exits.
Edit [sources.yaml](configs/sources.yaml) for report sources and
[discovery-sources.yaml](configs/discovery-sources.yaml) for discovery feeds.
The defaults include 32 report sources and 51 discovery sources. Each report source
contributes up to 15 summaries; discovery sources feed the monitor only.

## Data and limits

Versioned JSON and Markdown are the original records. HTML, PDF, and Notion are reading
copies. Existing report revisions are never overwritten. Network failures, rate limits,
and pending verification keep their own status; missing usage is never counted as zero.
Runtime data stays local by default. [Usage](docs/usage.md) covers paths and recovery.

Source availability, model latency, and evidence quality affect delivery. The configured
one-hour budget stops new work from being dispatched; it does not guarantee that all sources,
PDF generation, and evaluation finish within an hour. The
[technical-debt tracker](docs/exec-plans/tech-debt-tracker.md) records known gaps.

Experimental explainers support evidence binding, language reviews, and illustrated reading.
Current-news publishing still awaits freshness adapters and formal acceptance. Speech and video
have not shipped. See [Explainers](docs/explainers.md) and the [roadmap](docs/roadmap.md).

## Contributing

Start with the [development guide](docs/development.md). The [architecture](ARCHITECTURE.md)
explains system boundaries, and [AGENTS.md](AGENTS.md) guides agents editing the repository.
Release history is in [CHANGELOG.md](CHANGELOG.md).

[MIT License](LICENSE) © Wang Mingfeng
