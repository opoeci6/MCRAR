"""`mcrar llm status|test`, `mcrar search --llm` and `mcrar ratings eval --llm` (fake provider)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from recommend_support import (
    QUERY_TEXTS,
    FakeProvider,
    MapEmbedder,
    build_catalog,
    fake_llm_client,
    parse_reply,
)
from typer.testing import CliRunner

from mcrar import cli
from mcrar.catalog import open_catalog
from mcrar.cli import app
from mcrar.config import get_settings
from mcrar.llm.base import LLMAuthError, LLMTimeout
from mcrar.recommend import SearchFilters
from mcrar.recommend.ratings import filters_to_json

runner = CliRunner()
KEY = "sk-FAKE-KEY-0123456789"
TEXT = "tense stealth level"


class Loader:
    def __init__(self) -> None:
        self.loaded: list[MapEmbedder] = []

    def __call__(self, key: str, settings: object, **kwargs: object) -> MapEmbedder:
        embedder = MapEmbedder(QUERY_TEXTS, key=key)
        self.loaded.append(embedder)
        return embedder


@pytest.fixture
def loader(monkeypatch: pytest.MonkeyPatch) -> Loader:
    fake = Loader()
    monkeypatch.setattr(cli, "_load_embedder", fake)
    monkeypatch.setattr(cli, "_torch_available", lambda: True)
    return fake


@pytest.fixture
def catalog() -> dict[str, int]:
    with open_catalog(get_settings()) as repo:
        return build_catalog(repo)


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider, **llm: Any) -> None:
    client = fake_llm_client(provider, **llm)
    monkeypatch.setattr(cli, "_llm_client", lambda settings: client)


# -- llm status / test -----------------------------------------------------------------------


def test_status_of_the_defaults() -> None:
    result = runner.invoke(app, ["llm", "status"])
    assert result.exit_code == 0, result.output
    assert "Provider: OpenAI (openai)" in result.output and "Model: gpt-6-luna" in result.output
    assert "not ready, disabled" in result.output


def test_status_says_how_to_store_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_LLM__ENABLED", "true")
    result = runner.invoke(app, ["llm", "status"])
    assert "mcrar secrets set llm_api_key_openai" in result.output
    monkeypatch.setenv("MCRAR_SECRET_LLM_API_KEY_OPENAI", KEY)
    ready = runner.invoke(app, ["llm", "status", "--json"])
    assert json.loads(ready.output)["ready"] is True
    assert KEY not in ready.output and KEY not in result.output


def test_test_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    use_provider(monkeypatch, FakeProvider({"ok": True}))
    result = runner.invoke(app, ["llm", "test"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith(
        "OK: fake-model replied in "
    ) and result.output.strip().endswith("ms")


def test_test_failure_exits_1_with_the_safe_message(monkeypatch: pytest.MonkeyPatch) -> None:
    message = "Authentication failed (HTTP 401). Check the API key."
    use_provider(monkeypatch, FakeProvider(LLMAuthError(message)))
    result = runner.invoke(app, ["llm", "test"])
    assert result.exit_code == 1 and f"error: {message}" in result.output


def test_test_without_a_key_names_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(app, ["llm", "test"])
    assert result.exit_code == 1 and "No API key is set for OpenAI." in result.output


# -- search --llm ----------------------------------------------------------------------------


def test_search_llm_reads_the_query_and_says_so(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    provider = FakeProvider(parse_reply(semantic_text=TEXT, moods=["dark"]))
    use_provider(monkeypatch, provider)  # llm.enabled is false: --llm is enough
    result = runner.invoke(app, ["search", "niveau furtif tendu", "--llm", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert "LLM: fake-model read the query" in result.output
    assert 'understood as "tense stealth level"' in result.output and "(LLM)" in result.output
    assert [TEXT] in loader.loaded[0].calls
    as_json = runner.invoke(app, ["search", "niveau furtif tendu", "--llm", "--json"])
    data = json.loads(as_json.stdout)
    assert data["llm"]["used"] is True and data["llm"]["cached"] is False
    assert data["parsed"]["source"] == "llm"
    assert len(provider.calls) == 2  # separate processes in real life: no shared cache


def test_search_llm_failure_falls_back_and_prints_why(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    use_provider(monkeypatch, FakeProvider(LLMTimeout("Timed out after 10 s.")))
    result = runner.invoke(app, ["search", TEXT, "--llm", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "LLM: not used (Timed out after 10 s.)" in result.output
    assert "used the rule parser" in result.output


def test_search_llm_without_a_key_falls_back(loader: Loader, catalog: dict[str, int]) -> None:
    result = runner.invoke(app, ["search", TEXT, "--llm", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "LLM: not used (No API key is set for OpenAI.)" in result.output


def test_search_without_llm_never_calls_it(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    provider = FakeProvider(parse_reply(semantic_text=TEXT))
    use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["search", TEXT, "--limit", "2"])
    assert result.exit_code == 0 and "LLM" not in result.output and provider.calls == []


def test_search_uses_the_llm_when_it_is_enabled_in_the_settings(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    monkeypatch.setenv("MCRAR_LLM__ENABLED", "true")
    provider = FakeProvider(parse_reply(semantic_text=TEXT))
    use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["search", "x y", "--limit", "2"])
    assert result.exit_code == 0 and "LLM: fake-model read the query" in result.output


def test_a_filter_only_search_prints_no_llm_line(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    provider = FakeProvider(parse_reply())
    use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["search", "--vocal", "--llm"])
    assert result.exit_code == 0 and "LLM" not in result.output and provider.calls == []


def test_a_search_failure_message_is_redacted(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"failed GET https://api.example.test/v1?client_id={KEY} now")

    monkeypatch.setattr("mcrar.recommend.SearchService.search", boom)
    result = runner.invoke(app, ["search", TEXT])
    assert result.exit_code == 1 and "search failed (RuntimeError:" in result.output
    assert KEY not in result.output and "api.example.test" not in result.output


# -- ratings eval --llm ----------------------------------------------------------------------


def rate(text: str, scores: dict[int, int]) -> None:
    with open_catalog(get_settings()) as repo:
        for track_id, score in scores.items():
            repo.set_rating(
                f"text:{text}",
                track_id,
                score,
                query_text=text,
                filters_json=filters_to_json(SearchFilters()),
            )


def test_eval_llm_reports_the_parser_and_the_fallbacks(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    rate(TEXT, {catalog["Shadow Walk"]: 2})
    rate("epic battle", {catalog["Epic Quest"]: 1})
    answers = {
        TEXT: parse_reply(semantic_text=TEXT),
        "epic battle": LLMTimeout("Timed out after 10 s."),
    }

    def reply(call: dict[str, Any]) -> Any:
        return answers[call["messages"][1]["content"].split("\n")[0].removeprefix("Search: ")]

    provider = FakeProvider(reply)
    use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["ratings", "eval", "--llm"])
    assert result.exit_code == 0, result.output
    assert "Parser: LLM; 1 of 2 text queries fell back to the rules" in result.output
    as_json = runner.invoke(app, ["ratings", "eval", "--llm", "--json"])
    data = json.loads(as_json.stdout)
    assert (data["parser"], data["llm_queries"], data["llm_fell_back"]) == ("llm", 2, 1)


def test_eval_uses_the_rules_unless_asked(
    monkeypatch: pytest.MonkeyPatch, loader: Loader, catalog: dict[str, int]
) -> None:
    rate(TEXT, {catalog["Shadow Walk"]: 2})
    provider = FakeProvider(parse_reply(semantic_text=TEXT))
    use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["ratings", "eval"])
    assert result.exit_code == 0 and "Parser:" not in result.output and provider.calls == []
    assert "parser" not in json.loads(runner.invoke(app, ["ratings", "eval", "--json"]).stdout)
