# Native Windows Setup

**Status:** Operational reference
**Last code verification:** 2026-08-23
**Documentation catalog:** [`docs/README.md`](../docs/README.md)

## Hermes Home

Native Windows Hermes stores its active profile under `%LOCALAPPDATA%\hermes`, not
`%USERPROFILE%\.hermes`. The default locations are:

```text
%LOCALAPPDATA%\hermes\skills
%LOCALAPPDATA%\hermes\daily-intelligence
%LOCALAPPDATA%\hermes\browser-profiles\daily-intelligence
%LOCALAPPDATA%\hermes\.env
```

`HERMES_HOME` overrides this root. Unix and WSL use `~/.hermes` when no override is set.

## Installation and moving the directory

Put the Skill in its final directory before installing the Python package. Use an editable install
for development only:

```powershell
python -m pip install -e .
```

For a stable installed copy, use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

`ExecutionPolicy Bypass` applies only to that child process; it does not change the machine or user policy. The installer mirrors the repository into the real Hermes skills directory while excluding secrets, runtime data, browser profiles, authenticated HTML, screenshots and Playwright debug output.

An editable install records the source directory. Uninstall it before moving or renaming that
directory, then reinstall from the new location:

```powershell
python -m pip uninstall daily-intelligence-skill
```

## Environment

The CLI loads missing values from `%LOCALAPPDATA%\hermes\.env` automatically and does not override
variables already supplied by the process. Do not use `export $(grep ... | xargs)`: it mishandles
quoted values and can expose secrets.

Hermes usage hooks must run with UTF-8 mode when their stdin may contain Chinese or other
non-ASCII metadata. Set this on the process that launches Hermes (and therefore its child hooks):

```powershell
$env:PYTHONUTF8 = "1"
hermes hooks doctor
```

Without `PYTHONUTF8=1`, redirected Windows Python I/O may use a legacy code page and a healthy
hook executable can fail before recording its observation. Configure the hook command with the
absolute installed executable under `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\` so scheduled
processes do not depend on an interactive `PATH`. `hermes hooks doctor` should report the approved
pre-request, post-request, and request-error observers as unchanged and observer-only. The current
Cron CLI still cannot inject a job-specific SignalTrail task environment; direct isolated processes
can be measured per request, while scheduled evaluators require the documented partial/durable-log
recovery boundary.

## Canonical data root

The first normal command binds one runtime root in `%LOCALAPPDATA%\hermes\state\daily-intelligence-data-root.json`. A later command using another root fails before it reads or writes run artifacts. Inspect or deliberately migrate the binding with:

```powershell
daily-intel --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root status
daily-intel --data-dir "$env:LOCALAPPDATA\hermes\daily-intelligence" data-root adopt
```

Adoption does not merge or delete an old directory.

## Local HTML and PDF

Every successful `finalize-edition` creates a local reading page, A4 PDF, and archive index under:

```text
%LOCALAPPDATA%\hermes\daily-intelligence\reports\index.html
```

This does not require Notion credentials. Windows uses installed Edge to print a self-contained HTML projection after eagerly loading every embedded image; PDF-bound images are resampled to the print boundary and transcoded before embedding, so the result does not depend on the authenticated browser profile, external network requests, or local media paths. If headless Edge is unavailable, ReportLab produces a simpler PDF and applies the same bounded image projection. Set `output.pdf_engine: reportlab` in `configs/sources.yaml` to force that fallback, or remove `pdf` from `output.formats` to generate HTML only. `output.pdf_max_bytes` defaults to 52,428,800 bytes; projection returns explicit timing/size fields and preserves an over-budget PDF with a warning for diagnosis.

`open_after_finalize` defaults to false so 06:00/18:00 tasks do not open a window. Set it true only for interactive use. `copy_html_to_desktop` defaults to true in the bundled configuration, so every finalized edition also writes `daily-intelligence-YYYY-MM-DD-EDITION-rN.html` to the current user's Desktop. The desktop projection embeds validated cached images as data URIs so the HTML can be moved to another device as one file; archive and eventual PDF links remain absolute local links. Set an absolute `output.desktop_dir` to override the detected Desktop. A failed desktop write is reported as `desktop_html_error` without rolling back the local JSON/Markdown/HTML truth. HTML/PDF may be refreshed after independent evaluation; JSON/Markdown remain the immutable facts.

## Manual source verification

`run-edition` never opens the verification queue by default. Run collection first, then start manual verification only when ready:

```powershell
daily-intel run-edition --edition morning --profile-dir "$env:LOCALAPPDATA\hermes\browser-profiles\daily-intelligence"
daily-intel verify-source reuters --browser-channel msedge
daily-intel verify-pending --index "C:\path\to\index.json" --browser-channel msedge --timeout-seconds 300
```

After collection, failed, challenged, or rate-limited pages remain pending without opening Edge. `verify-pending` is the recommended manual path. Explicit `--open-verification` remains compatible but blocks until completion or timeout; `--unattended` remains a no-window compatibility flag and is already the default behavior.

Windows defaults to installed Microsoft Edge when no channel override is present. Complete the
legitimate publisher login or verification in the visible dedicated Edge profile. Cookies and login
state persist in that profile for later runs. The CLI does not require terminal input: it detects a
cleared challenge, immediately extracts the current authenticated page, and atomically adopts a new
index. A closed tab, HTTP 403, extraction failure, or timeout is skipped and remains pending with
its original link. Do not run `resume` after `verify-pending`; use it only for a later diagnostic
retry. Scheduled cron/gateway jobs must not pass `--open-verification`; they keep challenges pending and publish a partial report instead
of waiting for a GUI.
