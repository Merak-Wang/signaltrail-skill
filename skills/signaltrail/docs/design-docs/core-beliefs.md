# Engineering Principles

**Status:** Verified
**Owner:** Repository maintainers
**Last verified:** 2026-08-28

1. **Source of truth.** Versioned code, schemas, tests, and linked engineering records explain
   current behavior and the decisions that shaped it.
2. **Scoped entry documents.** Repository entry points summarize boundaries and route readers to
   task-specific code, tests, and references.
3. **Deterministic responsibilities.** Python owns identity, state transitions, validation,
   limits, and persistence. Models perform bounded selection and writing against explicit inputs.
4. **Failure-state preservation.** Access denial, rate limiting, and partial collection retain
   distinct statuses and recovery information throughout the pipeline.
5. **Projection authority.** Versioned JSON and Markdown are authoritative. HTML, PDF, desktop
   copies, and Notion are reproducible delivery projections.
6. **Bounded semantic work.** Evidence packets, authoring batches, analysis dossiers, and model
   usage have explicit limits even when collection covers a broad source set.
7. **Compatibility.** Legacy source-index shapes remain readable until a tested migration and
   release note define their removal.
8. **Documentation verification.** CI checks catalog coverage, translation pairs, link integrity,
   verification dates, and entry-document size.
9. **Generated artifacts.** Canonical sources are edited directly; release and installation
   snapshots are rebuilt by their packaging process.
10. **Visible technical debt.** Known gaps carry evidence, impact, and a verifiable exit condition
    in the technical-debt tracker or an active execution plan.
11. **Code documentation.** Maintained definitions describe logic, input provenance, consumed
    fields, and downstream output meaning in concise Chinese. Inline notes cover non-obvious
    safety, state, compatibility, concurrency, and recovery decisions.
