# Repository Guidelines

## Project Structure & Module Organization

Runtime code lives in `server/` (MCP entry point, Qdrant retrieval, and runtime contracts); data tooling is in `scripts/`. The normalized index inputs are generated `corpus_md/` files and manually maintained `guidelines_md/` files. Raw or legacy sources are in `auditstandard_md/`, `ifrs_md/`, `Conceptual_framework_md/`, and `guidelines_raw/`. Tests live in `tests/`, recall evaluation in `eval/`, reports in `reports/`, index audit artifacts in `index/`, and design records in `docs/`.

## Build, Test, and Development Commands

- `.venv/bin/python scripts/normalize_corpus.py` regenerates and structurally validates `corpus_md/`.
- `.venv/bin/python scripts/build_index.py --stage export` refreshes embedding input without a Qdrant upsert.
- `.venv/bin/python scripts/build_index.py` runs the complete embedding, indexing, upsert, and smoke-check pipeline; it requires Qdrant credentials and can be slow on CPU.
- `.venv/bin/python -m server.mcp_server` starts the stdio MCP server.
- `.venv/bin/pytest tests/test_acceptance.py -v` runs acceptance cases A1–A10 against live Qdrant.
- `.venv/bin/python eval/score_interpretation.py reports/해석_2100.md 2100` scores a report against the routing gold set.

No dependency manifest or lint command is tracked.

## Coding Style & Naming Conventions

Use four-space indentation and follow surrounding PEP 8-style Python. Name functions and variables `snake_case`, classes `CapWords`, and constants `UPPER_SNAKE_CASE`. Keep concise docstrings; prefer `pathlib.Path` and explicit UTF-8 for corpus I/O. No formatter or line-length policy is configured, so avoid unrelated reformatting. Preserve Korean domain terms and IDs such as `KIFRS::1115::31`; quote shell paths containing Korean text, spaces, or parentheses.

## Testing Guidelines

Pytest acceptance tests are the only automated suite; there is no configured coverage threshold. They require `.env` values for `QDRANT_URL` and `QDRANT_API_KEY` plus the embedding-model dependencies/cache. Add contract scenarios to `tests/test_acceptance.py` using `test_a<N>_<behavior>`. After normalization or index changes, run the converter's built-in assertions and the full acceptance suite.

## Data and Configuration Safety

Never commit `.env`, API keys, embedding binaries, caches, or source working papers. Do not hand-edit generated `corpus_md/`; change its source or converter and regenerate it. `guidelines_md/` is the manual source of truth, so document corrections in its README.

## Commit & Pull Request Guidelines

History favors concise Korean subjects naming scope and outcome, often `scope: result`; Conventional Commit prefixes are not used. For substantial changes, add a bullet-list body covering affected paths, decisions, counts, and verification. Pull requests should summarize scope, identify regenerated artifacts or Qdrant contract changes, cite sources for corpus corrections, link relevant issues, and report exact commands and results. No PR template exists.
