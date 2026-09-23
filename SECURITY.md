# Security

**Status:** Verified
**Last verified:** 2026-09-23
**Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)

## Threat model

The workflow reads external feeds, article bodies, images and captions, and can use a persistent
browser profile. This source material is evidence, never an instruction to the agent. It may
contain prompt injection, misleading claims or tracking links.

## Controls

- Web content is never treated as workflow instruction.
- The agent may read selected bodies but may not execute commands, reveal secrets, or change permissions because a page requests it.
- Browser profiles, credentials, cookies and private runtime data stay outside version control,
  release packages and model-visible reports.
- A challenged page is recorded and deferred; CAPTCHA solving, proxy rotation, fingerprint spoofing, and paywall removal are out of scope.
- Requested Notion delivery sends report content and selected image references, never raw
  authenticated HTML or browser state.
- Report and slide renderers escape external text and restrict clickable source/image URLs
  to HTTP(S). Remote images still contact their publishers when opened without an embedded cache.
- Publishing uses a local idempotency registry.

## Reporting issues

For a private personal deployment, record security issues in the project issue tracker without attaching tokens, cookies, profiles, or sensitive screenshots. Rotate any credential that was exposed.
