"""The model registry, the commercial-mode gate and the lazy-import guarantee."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from mcrar.config import get_settings
from mcrar.ml import MODELS, CommercialModeError, ModelError, get_spec, parse_model_keys
from mcrar.ml.registry import check_allowed, is_allowed


def test_registry_has_the_three_models() -> None:
    assert list(MODELS) == ["clap", "glap", "muq-mulan"]
    assert {k: s.sample_rate for k, s in MODELS.items()} == {
        "clap": 48_000,
        "glap": 16_000,
        "muq-mulan": 24_000,
    }
    assert {k: s.dim for k, s in MODELS.items()} == {"clap": 512, "glap": 1024, "muq-mulan": 512}
    assert {k: s.commercial_ok for k, s in MODELS.items()} == {
        "clap": True,
        "glap": True,
        "muq-mulan": False,
    }


def test_every_repository_is_pinned_to_a_full_commit_hash() -> None:
    for spec in MODELS.values():
        assert spec.pins[0] is spec.weights
        for pin in spec.pins:
            assert re.fullmatch(r"[0-9a-f]{40}", pin.revision), pin
            assert pin.files, pin


def test_muq_mulan_pins_the_repositories_it_would_otherwise_fetch_by_name() -> None:
    repos = {pin.repo for pin in get_spec("muq-mulan").pins}
    assert repos == {
        "OpenMuQ/MuQ-MuLan-large",
        "OpenMuQ/MuQ-large-msd-iter",
        "FacebookAI/xlm-roberta-base",
    }


def test_model_id_is_key_and_short_revision() -> None:
    spec = get_spec("clap")
    assert spec.model_id == f"clap@{spec.revision[:7]}"
    assert spec.model_id == "clap@195c3a3"


def test_unknown_model_lists_the_known_ones() -> None:
    with pytest.raises(ModelError, match="unknown model 'nope'; choose from: clap, glap"):
        get_spec("nope")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("clap", ["clap"]),
        (" clap , glap,", ["clap", "glap"]),
        ("glap,clap,glap", ["glap", "clap"]),
        (["muq-mulan"], ["muq-mulan"]),
    ],
)
def test_parse_model_keys(value: str | list[str], expected: list[str]) -> None:
    assert parse_model_keys(value) == expected


@pytest.mark.parametrize("value", ["", " , ", "clap,nope"])
def test_parse_model_keys_rejects_empty_and_unknown(value: str) -> None:
    with pytest.raises(ModelError):
        parse_model_keys(value)


def test_commercial_mode_refuses_non_commercial_models() -> None:
    settings = get_settings(commercial_mode=True)
    assert is_allowed(get_spec("clap"), settings)
    assert not is_allowed(get_spec("muq-mulan"), settings)
    check_allowed(get_spec("glap"), settings)
    with pytest.raises(CommercialModeError) as err:
        check_allowed(get_spec("muq-mulan"), settings)
    message = str(err.value)
    assert "MCRAR_COMMERCIAL_MODE=false" in message
    assert "commercial_mode = false" in message
    assert "CC-BY-NC-4.0" in message


def test_commercial_mode_off_allows_everything() -> None:
    settings = get_settings(commercial_mode=False)
    for spec in MODELS.values():
        check_allowed(spec, settings)


def test_commercial_mode_is_on_by_default() -> None:
    assert get_settings().commercial_mode is True


def test_load_embedder_checks_the_licence_before_touching_torch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcrar.ml.embedders import load_embedder, loader

    def boom() -> None:
        raise AssertionError("torch must not be imported for a refused model")

    monkeypatch.setattr(loader, "_torch", boom)
    with pytest.raises(CommercialModeError, match="MCRAR_COMMERCIAL_MODE=false"):
        load_embedder("muq-mulan", settings=get_settings(commercial_mode=True))


def test_load_embedder_rejects_unknown_key() -> None:
    from mcrar.ml.embedders import load_embedder

    with pytest.raises(ModelError, match="unknown model"):
        load_embedder("nope", settings=get_settings())


def test_importing_the_cli_and_pipeline_does_not_import_torch() -> None:
    code = (
        "import sys\n"
        "import mcrar.cli, mcrar.ingest, mcrar.ml, mcrar.ml.embedders, mcrar.ml.benchmark\n"
        "heavy = ('torch', 'transformers', 'huggingface_hub', 'muq')\n"
        "bad = [m for m in heavy if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
