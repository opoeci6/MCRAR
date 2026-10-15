"""Registry validation, artifact hashes, and entry selection protect runtime consumers."""

from __future__ import annotations

from copy import deepcopy

import pytest
from tagging_support import register

from mcrar.config import get_settings
from mcrar.ml.tagging import load_taggers, select_entry
from mcrar.ml.tagging.registry import read_registry, validate_registry


def test_selection_best_overall_test_split_and_no_entry() -> None:
    safe = {
        "id": "safe",
        "commercial_ok": True,
        "metrics": {"split": "test", "primary": "macro_f1", "macro_f1": 0.4},
    }
    nc = {
        "id": "nc",
        "commercial_ok": False,
        "metrics": {"split": "test", "primary": "macro_f1", "macro_f1": 0.9},
    }
    spec = {"kind": "single_label", "entries": [safe, nc]}
    assert select_entry(spec)["id"] == "nc"  # best overall wins, whatever the licence
    assert select_entry({**spec, "entries": [safe]})["id"] == "safe"
    tied = {**nc, "id": "zz", "metrics": {**nc["metrics"]}}
    assert select_entry({**spec, "entries": [nc, tied]})["id"] == "zz"  # ties: larger id
    nan = {**nc, "metrics": {**nc["metrics"], "macro_f1": float("nan")}}
    assert select_entry({**spec, "entries": [nan, safe]})["id"] == "safe"
    assert select_entry({**spec, "entries": []}) is None
    assert (
        select_entry(
            {**spec, "entries": [{**safe, "metrics": {**safe["metrics"], "split": "validation"}}]}
        )
        is None
    )


def test_schema_and_content_hash_validation() -> None:
    settings = get_settings()
    registry = register(settings)
    validate_registry(registry, settings.models_dir)
    assert load_taggers(settings)[0].entry_id == registry["label_sets"]["genre"]["entries"][0]["id"]
    bad = deepcopy(registry)
    bad["schema"] = 2
    with pytest.raises(ValueError, match="schema"):
        validate_registry(bad)
    bad = deepcopy(registry)
    bad["label_sets"]["genre"]["entries"][0]["data_license"] = "CC BY-NC 4.0"
    with pytest.raises(ValueError, match="non-commercial"):
        validate_registry(bad)
    bad = deepcopy(registry)
    bad["label_sets"]["genre"]["entries"][0]["variant"] = "../../outside"
    with pytest.raises(ValueError, match="stable identifier"):
        validate_registry(bad)
    entry = registry["label_sets"]["genre"]["entries"][0]
    with (settings.models_dir / entry["file"]).open("ab") as stream:
        stream.write(b"altered")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_registry(settings)
