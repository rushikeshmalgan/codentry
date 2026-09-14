# packages/schemas

Language-neutral contracts shared between `apps/web` (TypeScript) and
`services/ai-review` (Python), so the two sides can't silently drift apart on
what a "finding" looks like.

## Contents

- `review.schema.json` — JSON Schema (draft 2020-12) for the normalized
  `Finding` object. This is the single source of truth for the shape every
  ESLint, Semgrep, and AI finding must conform to.

## Status (Phase 1)

This schema is **not yet consumed by any code**. It exists now so the
contract is fixed and reviewable before Phase 3 (static analysis) and
Phase 4 (Claude AI review) both need to produce objects matching it.

## Consumption plan

- **Phase 3** (`services/ai-review`): mirror this schema as a Pydantic model
  used to validate normalized ESLint/Semgrep output before it's written to
  the `findings` table.
- **Phase 4** (`services/ai-review`): the same Pydantic model (with
  `confidence`, `reasoning`, `evidence_span` required instead of optional)
  is used as Claude's forced structured-output schema, so malformed AI
  output is rejected before it ever reaches the database.
- If `apps/web` ever needs to read findings directly (e.g. for the optional
  internal dashboard, PRD FR-8), mirror this schema as a TypeScript type by
  hand rather than introducing a codegen step — the schema is small enough
  that hand-mirroring is less overhead than a build tool, until proven
  otherwise.

## Versioning

Treat a change to `required`, an enum, or a field's type as breaking:
bump the `$id` URL's implicit version (e.g. add `/v2/`) rather than editing
in place, so a running service pinned to the old shape doesn't silently
start receiving fields it doesn't expect. Additive, optional fields don't
require a version bump.
