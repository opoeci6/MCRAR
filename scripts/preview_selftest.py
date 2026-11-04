"""Self-test of the portable preview build, run by scripts/build-preview.ps1 with the staged Python.

Run it as ``python -I preview_selftest.py`` with MCRAR_HOME set to the staged app folder. It checks
that the imports the app needs work, that torch is the CPU build, that the desktop window stack
(pywebview, pythonnet and the WebView2 DLLs) is complete and loads, that the package data made it
into the wheel and that the app finds its home, models and frontend. Exit code 0 means OK.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import sys
import tomllib
from pathlib import Path


def check_desktop_stack() -> None:
    """The window needs pywebview, its WebView2 DLLs, pythonnet and the .NET bridge.

    ``import clr`` loads the .NET Framework that Windows 10/11 ships, and the two platform
    modules load the WebView2 assemblies; none of them opens a window, writes outside the stage
    or needs the WebView2 runtime itself, so they are safe here and catch a missing DLL at build
    time instead of on the user's PC.
    """
    import clr_loader  # noqa: F401
    import pythonnet
    import webview

    package = Path(webview.__file__).parent
    for relative in (
        "lib/Microsoft.Web.WebView2.Core.dll",
        "lib/Microsoft.Web.WebView2.WinForms.dll",
        "lib/runtimes/win-x64/native/WebView2Loader.dll",
    ):
        assert (package / relative).is_file(), f"webview/{relative} is missing"
    assert (Path(pythonnet.__file__).parent / "runtime" / "Python.Runtime.dll").is_file()
    assert (Path(clr_loader.__file__).parent / "ffi" / "dlls" / "amd64" / "ClrLoader.dll").is_file()
    if sys.platform == "win32":
        import clr  # noqa: F401
        import webview.platforms.edgechromium  # noqa: F401
        import webview.platforms.winforms  # noqa: F401
    print("desktop window stack OK (pywebview, pythonnet, WebView2 DLLs)")


def main() -> int:
    import mcrar
    import mcrar.cli  # noqa: F401  (the CLI must import without side effects)
    import mcrar.desktop  # noqa: F401

    check_desktop_stack()

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
