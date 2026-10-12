# AGENTS.md

Instructions for coding agents (Codex and others) working in this repository. Humans: see
`README.md` and `docs/dev-setup.md`.

MCRAR is an ML music recommender for listeners and indie game developers. Python backend
(`backend/`, package `mcrar`, managed by uv), React + Vite + TypeScript frontend (`frontend/`).
The product plan is `docs/PLAN.md`. Work handed to a collaborator has its own spec under
`docs/handover/`, and that spec wins over this file where they differ.

## 1. Environment: everything stays inside the repo

The owner's hard requirement: **no tool, package, cache or setting may be installed or changed
outside this folder.**

- First-time setup (Windows): `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1`.
  It downloads pinned uv and Node.js into `.tools/` (SHA-256 checked), a managed Python 3.11 into
  `.tools/python`, then runs `uv sync --extra ml` (CUDA PyTorch included) and `npm ci`.
- **Run every command through the env wrapper.** Agent shells do not keep state between calls,
  so prefix each command:
  - Git Bash: `scripts/with-env.sh <cmd> [args]`
  - PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\with-env.ps1 <cmd> [args]`
  - Example: `scripts/with-env.sh uv run --directory backend pytest -q`
- Never run `pip install --user`, `npm -g`, `winget`, `choco`, `setx`, `conda`, a global
  `uv tool install`, registry writes or user-profile edits. Never use the system `python` or
  `node`: use `uv run python ...` and the project's `npm`.
- Add Python dependencies only with `scripts/with-env.sh uv add --directory backend <pkg>` (or
  `--optional ml` for ML-only packages), which updates `backend/uv.lock`. Say why in your summary.
- Model weights go to `.cache/huggingface` (`HF_HOME`), datasets and the catalog DB to `data/`,
  trained heads to `models/`. Paths are repo-relative via `mcrar.config.Settings`.
- `scripts/with-env.sh uv run --directory backend mcrar doctor` fails if the toolchain is not
  project-local.

## 2. Commands

```bash
scripts/with-env.sh uv run --directory backend pytest -q                 # default suite, no network
scripts/with-env.sh uv run --directory backend pytest -q -m models       # real models (GPU, downloads weights)
scripts/with-env.sh uv run --directory backend ruff check .
scripts/with-env.sh uv run --directory backend ruff format --check .
scripts/with-env.sh npm --prefix frontend run lint
scripts/with-env.sh npm --prefix frontend run build
scripts/with-env.sh uv run --directory backend mcrar --help              # the CLI
```

All of these must pass before you hand work back. CI (`.github/workflows/ci.yml`) runs the
default suite, ruff and the frontend build on every push and pull request.

## 3. Code conventions

- Read the neighbouring code first and match it: `from __future__ import annotations`, frozen
  dataclasses for records, module docstrings that state the design, ruff (line length 100, rules
  E/F/I/UP/B). Keep comment density similar to the surrounding code.
- `mcrar.catalog.CatalogRepository` is the only place with SQL. Do not query SQLite elsewhere.
- The CLI (`backend/src/mcrar/cli.py`, typer) never imports torch at module level. Errors print
  `error: <message>` to stderr and exit 1, never a traceback.
- Torch, transformers and model code are imported lazily (inside functions) so the default test
  suite and the CLI run without the `ml` extra.
- Do not change public interfaces other code depends on (catalog schema, `Stage` protocol,
  `Embedder` protocol, the model registry's pinned revisions) unless your spec says so. If you
  think one must change, stop and say so in your summary instead.

## 4. Tests

- Tests live in `backend/tests/<area>/`. There are no `__init__.py` files (pytest prepend import
  mode), so **every test file basename must be unique across the whole repo**. Use the area
  prefix: `test_ml_tagging_*.py`, `test_ingest_*.py`, and so on. Shared helpers go in a
  non-test module in the same folder (for example `ml_support.py`).
- **No network in the default suite.** Use `httpx.MockTransport`, fakes and synthetic audio
  generated with numpy and soundfile. Never commit binary audio fixtures.
- Tests that load real models carry `@pytest.mark.models` and are skipped unless run with
  `-m models`. Use `FakeEmbedder` (`backend/tests/ml/ml_support.py`) everywhere else.
- **The default suite must also pass without the `ml` extra** (no torch), because CI installs
  plain `uv sync`. A test that fakes a model must also fake "torch is available" (for example
  `monkeypatch.setattr(cli, "_torch_available", lambda: True)`) instead of relying on the
  machine. To check like CI does, sync into a scratch venv without the extra:
  `UV_PROJECT_ENVIRONMENT=<tmp>/ci-venv uv sync --directory backend --locked`, then run pytest with
  the same variable set.
- Never weaken an existing test to make a change pass. If a test is wrong, say why in your summary.

## 5. Secrets and data

- API keys live in `.secrets/` (git-ignored) through `mcrar secrets set <name>`, or in
  `MCRAR_SECRET_<NAME>` environment variables. Never print, log, commit or put a secret in a URL
  you show. The Jamendo client id is a secret.
- Never commit anything under `.secrets/`, `.tools/`, `.cache/`, `data/` or `config/settings.toml`.
  `backend/tests/test_repo_hygiene.py` enforces the ignore rules.
- Under `models/`, only `models/heads/` and `models/registry.json` are committed. Every head's
  training-data licence must be recorded in `registry.json`.
- Licences matter in this project. Non-commercial models or data (for example MuQ-MuLan weights
  or MTG-Jamendo labels) must be flagged `commercial_ok: false` and are refused while
  `Settings.commercial_mode` is true (the default).

## 6. Git workflow

- Branch from `dev` (never commit to `main` or `dev` directly) and open a pull request into `dev`.
- One logical change per commit. Commit subject in the imperative, prefixed with the milestone,
  for example `M3b: add zero-shot tagger`.
- **Commits carry the human's identity, not the agent's.** The author must be the person
  responsible for the work, with the name and email of their GitHub account, so commits link to
  that account. Set it for this repository only (never `--global`):
  `git config user.name "<GitHub name>"` and `git config user.email "<GitHub email or
  ID+login@users.noreply.github.com>"`. Credit the agent with a trailer at the end of every
  commit message, for example `Co-authored-by: Codex <codex@openai.com>`. Before pushing, check
  with `git log --format='%an <%ae>%n%(trailers:key=Co-authored-by)' origin/dev..HEAD` that no
  commit is authored by an agent.
- Keep your diff inside the files your spec assigns to you. Another agent works on other
  milestones at the same time, so edits to shared files (`cli.py`, `pipeline.py`, `config.py`)
  should be the minimal registration your spec describes.
- Do not commit `.claude/` (the owner's local Claude Code settings) or files under `data/`.
