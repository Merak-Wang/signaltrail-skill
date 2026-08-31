# Examples

**Status:** Current showcase, historical compatibility samples, and synthetic test fixtures
**Last verified:** 2026-08-28

[简体中文](README.md) | [English](README.en.md)

This directory presents the product through a current edition, historical
compatibility samples, and synthetic test data.

## Current schema 2.0 showcase

[2026-08-25 morning r1](reports/2026-08-25-morning-r1.html) is a complete historical
snapshot of one full collection run:

- 30 of 32 configured sources produced output, preserving 424 briefs;
- the editorial layer selected 8 evidence events and produced 3 domain analyses plus
  1 cross-perspective synthesis;
- the independent quality evaluation scored 37/45 and discloses data-recency and
  evidence limitations;
- the HTML references 136 public image URLs, so its complete visual experience needs
  a network connection;
- the archive contains no credentials or local runtime paths.

Download the HTML file and open it locally for the complete interactive reading
experience. Public images are hosted by external sources and may become unavailable
over time.

## Historical schema 1.5 compatibility samples

These archived HTML editions verify that earlier reports remain readable:

| Edition | Collection scale | Editorial result |
| --- | ---: | ---: |
| [2026-07-24 morning r3](reports/2026-07-24-morning-r3.html) | 24 sources · 197 updates | 10 priority events |
| [2026-07-25 morning r1](reports/2026-07-25-morning-r1.html) | 29 sources · 235 updates | 10 priority events |

They retain the earlier **Daily Intelligence** masthead and exist only as historical
compatibility showcases. Current schema 2.0 reports use the **SignalTrail** brand and
add cross-perspective synthesis.

## Synthetic fixtures

`sample_input.json` is a synthetic input fixture. `sample_report.json` is a schema 1.4
legacy test fixture. They support automated tests, legacy-schema validation, and
output rendering; neither represents the current report contract.
`sample_input.json` also retains legacy status labels and is not authoritative for
current access-failure semantics.

- People, organizations, events, dates, and analysis are synthetic.
- `news.example` and `wire.example` are reserved example domains, not publishers.
- Fixtures support engineering validation and carry no factual or editorial authority.
