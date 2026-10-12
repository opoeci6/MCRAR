# Development setup

Everything development needs (uv, Node.js, Python, caches, model weights, secrets) lives inside the
repo folder. Nothing is installed or configured system-wide. Windows 10/11 only for now.

## First-time setup

From a fresh clone, in Git Bash:

```bash
scripts/bootstrap.sh
```

or in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

The default execution policy blocks `.ps1` files. Either use `-ExecutionPolicy Bypass` as above, or
relax it for the current PowerShell window only (process scope, nothing is persisted):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

Bootstrap is idempotent. It:

1. downloads the pinned uv and Node.js zips (versions and SHA-256 hashes in `scripts/toolchain.lock`) into
   `.tools/`, verifies the hashes and aborts on a mismatch;
2. runs `uv python install` into `.tools/python` (registry registration and `~/.local/bin` executables
   disabled);
3. runs `uv sync --extra ml` in `backend/` and `npm ci` in `frontend/`.

The first `npm` step is `npm install` only if `frontend/package-lock.json` does not exist yet.

### The `ml` extra (PyTorch and the text-audio models)

`uv sync --extra ml` adds CUDA PyTorch (from the official PyTorch wheel index, pinned in
`backend/pyproject.toml`), transformers and the MuQ-MuLan package. It grows `backend/.venv` by
about 2.3 GB (the CUDA runtime ships inside the torch wheel, so no CUDA toolkit is needed). The
model weights download on first use into `.cache/huggingface` (about 8.4 GB for all three
models). Without an NVIDIA GPU everything still runs on CPU, only slower.

- `uv run mcrar models list` shows each model, its licence and whether it is downloaded.
- `uv run pytest -q -m models` runs the tests that load the real models.
- MuQ-MuLan's weights are non-commercial (CC-BY-NC-4.0). It is refused unless
  `MCRAR_COMMERCIAL_MODE=false` (or `commercial_mode = false` in `config/settings.toml`).
- The default suite and the CLI work without the extra (`uv sync` alone); model tests then skip.
- Known exception to "nothing outside the repo": torch compiles a few small kernels (about
  250 KB) into the system temp folder.

## Daily commands

Load the project environment into the current shell (it only affects that session):

```powershell
. .\scripts\dev-env.ps1            # PowerShell (dot-source)
```

```bash
source scripts/dev-env.sh          # Git Bash
```

Then:

```bash
cd backend && uv run pytest -q
cd backend && uv run ruff check . && uv run ruff format --check .
cd backend && uv run mcrar doctor  # verifies the toolchain is project-local
cd frontend && npm run lint && npm run build
```

Run backend (http://127.0.0.1:8000) and frontend (http://localhost:5173, proxies `/api`) together:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev.ps1
```

### One-shot commands (agents and non-interactive shells)

Shells that do not keep state between calls should run each command through a wrapper that loads the
environment first:

```bash
scripts/with-env.sh uv run --directory backend pytest -q
scripts/with-env.sh npm --prefix frontend run build
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\with-env.ps1 uv --version
```

## What lives where

| Thing | Location (all gitignored) | How |
|---|---|---|
| uv binary | `.tools/uv/` | `scripts/bootstrap.ps1` (pinned, SHA-256 verified) |
| Node.js / npm | `.tools/node/` | portable zip, same |
| Python interpreter | `.tools/python/` | `UV_PYTHON_INSTALL_DIR`, `UV_PYTHON_PREFERENCE=only-managed` |
| Python venv | `backend/.venv/` | `uv sync` |
| uv tools / bin dirs | `.tools/uv-tools/`, `.tools/tool-bin/`, `.tools/python-bin/` | `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_PYTHON_BIN_DIR` |
| npm global prefix (accidental `-g`) | `.tools/npm-global/` | `npm_config_prefix` |
| uv cache | `.cache/uv/` | `UV_CACHE_DIR` |
| npm cache | `.cache/npm/` | `npm_config_cache` |
| Frontend modules | `frontend/node_modules/` | `npm ci` |
| Model weights and other caches | `.cache/huggingface/`, `.cache/torch/`, `.cache/numba/`, `.cache/matplotlib/` | `HF_HOME`, `TORCH_HOME`, `NUMBA_CACHE_DIR`, `MPLCONFIGDIR`, `XDG_CACHE_HOME` |
| Datasets, catalog DB, benchmark results | `data/` | config paths are repo-relative |
| Trained tag heads + registry (committed) | `models/heads/`, `models/registry.json` | everything else under `models/` is ignored |
| API keys (dev) | `.secrets/secrets.toml` | `SecretStore` `file` backend |
| Optional settings file | `config/settings.toml` | copy `config/settings.example.toml` |
| Build output | `build/`, `dist/` | PyInstaller / Vite |

Settings precedence: constructor args > `MCRAR_*` environment variables > `config/settings.toml` > defaults.
Secrets: `MCRAR_SECRET_<NAME>` environment variables always win over the configured backend.
Manage them with `mcrar secrets set|list|delete`. The `keyring` backend is opt-in
(`uv sync --extra keyring`) because it writes to Windows Credential Manager.

## Never install globally

Rules for everyone, including agents:

- Never run `pip install --user`, `npm -g` / `npm install --global`, `winget`, `choco`, `setx`, or
  `uv tool install` outside the project environment.
- Never write to the registry, the user profile or the user's PowerShell profile.
- Always run commands through the dev environment: `source scripts/dev-env.sh` /
  `. .\scripts\dev-env.ps1`, or, for single commands, `scripts/with-env.sh <cmd>` /
  `scripts\with-env.ps1 <cmd>`. System Python and Node must not be used.
- Run Python as `uv run python ...` (project interpreter). A bare `python` on the PATH is still the
  system one, because the project environment installs no `python` shim on purpose.
- Use `mcrar doctor` to check: it fails if the interpreter or any cache variable points outside the repo.

## System pieces we only check, never install

- The **NVIDIA GPU driver** (PyTorch wheels bundle the CUDA runtime, so no CUDA toolkit is needed).
  `mcrar doctor` looks for `nvidia-smi`; without it everything still runs on CPU.
- The **WebView2 runtime**, used by the desktop shell from milestone M11 (ships with Windows 10/11).
  `mcrar doctor` does a read-only registry lookup.

Both produce a warning, not a failure, when missing.
