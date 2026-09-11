# Examples

**Status:** Current showcase and synthetic test fixtures
**Last verified:** 2026-09-11

[简体中文](README.md) | [English](README.en.md)

This directory provides the current finished example and synthetic test data.

## Current schema 2.0 showcase

[Download the 2026-08-25 morning r1 HTML](https://github.com/Merak-Wang/signaltrail-skill/raw/refs/heads/main/examples/reports/2026-08-25-morning-r1.html)
is the current complete run example:

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

The showcase and README screenshots received the new masthead, palette, and source headings on
2026-09-11. Historical content, 424 news entries, 136 image references, and scores are unchanged.
The original floating directory and continuous reading remain in place.

## Synthetic fixtures

`sample_input.json` and `sample_report.json` support automated tests, compatibility
validation, and output rendering; neither represents the current report contract.

- People, organizations, events, dates, and analysis are synthetic.
- `news.example` and `wire.example` are reserved example domains, not publishers.
- Fixtures support engineering validation and carry no factual or editorial authority.
