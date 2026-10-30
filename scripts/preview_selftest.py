"""Self-test of the portable preview build, run by scripts/build-preview.ps1 with the staged Python.

Run it as ``python -I preview_selftest.py`` with MCRAR_HOME set to the staged app folder. It checks
that the imports the app needs work, that torch is the CPU build, that the package data made it
into the wheel and that the app finds its home, models and frontend. Exit code 0 means OK.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import sys
import tomllib
from pathlib import Path


def main() -> int:
    import mcrar
    import mcrar.cli  # noqa: F401  (the CLI must import without side effects)

    # The wheel must be installed into site-packages, not found through a source checkout.
    assert "site-packages" in Path(mcrar.__file__).parts, f"mcrar is not installed: {mcrar.__file__}"

    import librosa
    import muq  # noqa: F401
    import pyloudnorm  # noqa: F401
    import sklearn
    import soundfile
    import soxr  # noqa: F401
    import torch
    import torchaudio
    import transformers

    assert torch.__version__.endswith("+cpu"), f"not the CPU build of torch: {torch.__version__}"
    assert not torch.cuda.is_available()
    print(f"torch {torch.__version__}, torchaudio {torchaudio.__version__}")
    print(f"transformers {transformers.__version__}, scikit-learn {sklearn.__version__}")
    print(f"soundfile {soundfile.__version__}, librosa {librosa.__version__}, mcrar {mcrar.__version__}")

    package = importlib.resources.files("mcrar")
    prompts = sorted(package.joinpath("ml", "tagging", "prompts").iterdir(), key=lambda p: p.name)
    toml_files = [p for p in prompts if p.name.endswith(".toml")]
    assert len(toml_files) >= 5, f"tagging prompts missing from the wheel: {[p.name for p in prompts]}"
    for path in toml_files:
        tomllib.loads(path.read_text(encoding="utf-8"))
    checksums = json.loads(
        package.joinpath("ml", "datasets", "deam_checksums.json").read_text(encoding="utf-8")
    )
    assert checksums, "deam_checksums.json is empty"
    print(f"package data OK ({len(toml_files)} prompt files, {len(checksums)} checksum entries)")

    from mcrar.api.app import frontend_dist
    from mcrar.config import get_settings

    settings = get_settings()
    home = os.environ["MCRAR_HOME"]
    assert settings.home == Path(home).resolve(), f"home is {settings.home}, expected {home}"
    assert (settings.models_dir / "registry.json").is_file(), "models/registry.json missing"
    assert any((settings.models_dir / "heads").glob("*.npz")), "models/heads has no heads"
    assert (frontend_dist(settings) / "index.html").is_file(), "frontend/dist/index.html missing"
    print(f"home {settings.home}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
