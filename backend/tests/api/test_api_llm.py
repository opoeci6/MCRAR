"""The optional LLM over HTTP: status, test, search with the LLM parser, rerank, settings, import.

The provider is a fake (``FakeProvider``) behind the app's ``llm_provider_factory`` seam, so no
network is used. A recognisable fake key is stored as a secret to show it never leaves the server.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from api_support import ApiClient, IngestJamendo, make_client, wait_done
from recommend_support import FakeProvider, parse_reply

from mcrar.llm.base import LLMAuthError, LLMInvalidReply, LLMRateLimited, LLMTimeout
from mcrar.llm.presets import get_preset

KEY = "sk-FAKE-KEY-0123456789"
QUERY = {"text": "tense stealth level"}
CUSTOM = {"enabled": True, "preset": "custom", "model": "fake-model"}  # needs no key


class Factory:
    """The provider factory seam: records what it was asked to build and hands out one fake."""

    def __init__(self, reply: Any = None) -> None:
        self.provider = FakeProvider(reply if reply is not None else parse_reply())
        self.built: list[tuple[str, str, str, str | None]] = []

    def __call__(self, preset: Any, model: str, base_url: str, key: str | None) -> FakeProvider:
        self.built.append((preset.id, model, base_url, key))
        return self.provider


def client_for(tmp_path: Path, factory: Factory | None = None, **llm: Any) -> ApiClient:
    return make_client(
        tmp_path,
        llm_factory=factory or Factory(),
        settings_overrides={"llm": llm} if llm else None,
    )


def rerank_reply(*numbers: int, **extra: Any) -> dict[str, Any]:
    ranking = [{"n": n, "explanation": f"because {n}"} for n in numbers]
    return {
        "ranking": ranking,
        "verdict": "partial",
        "summary": "Meh.",
        "search_terms": ["x"],
    } | extra


# -- GET /api/llm and POST /api/llm/test -------------------------------------------------------


def test_status_reasons(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        body = client.get("/api/llm").json()
        assert body == {
            "enabled": False,
            "ready": False,
            "preset": "openai",
            "label": "OpenAI",
            "kind": "openai",
            "model": "gpt-6-luna",
            "reason": "disabled",
            "rerank_top_n": 20,
        }
        assert client.put("/api/settings", json={"llm": {"enabled": True}}).status_code == 200
        assert client.get("/api/llm").json()["reason"] == "missing_key"
        assert client.put("/api/secrets/llm_api_key_openai", json={"value": KEY}).status_code == 204
        ready = client.get("/api/llm").json()  # the key is read when asked: no reload needed
        assert ready["ready"] is True and ready["reason"] is None and ready["enabled"] is True
        assert KEY not in client.get("/api/llm").text
        client.put("/api/settings", json={"llm": {"preset": "custom", "model": ""}})
        assert client.get("/api/llm").json()["reason"] == "missing_model"
        client.put("/api/settings", json={"llm": {"model": "llama3", "rerank_top_n": 12}})
        body = client.get("/api/llm").json()
        assert (body["ready"], body["model"], body["rerank_top_n"]) == (True, "llama3", 12)


def test_the_test_route_ok_and_error(tmp_path: Path) -> None:
    factory = Factory({"ok": True})
    with client_for(tmp_path, factory) as client:  # disabled: testing still works
        client.put("/api/secrets/llm_api_key_openai", json={"value": KEY})
        body = client.post("/api/llm/test").json()
        assert body["ok"] is True and body["model"] == "fake-model"
        assert body["elapsed_ms"] >= 0
        assert factory.built == [("openai", "gpt-6-luna", "https://api.openai.com/v1", KEY)]
        factory.provider.reply = LLMAuthError(
            "Authentication failed (HTTP 401). Check the API key."
        )
        response = client.post("/api/llm/test")
        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "error": "Authentication failed (HTTP 401). Check the API key.",
        }
        factory.provider.reply = LLMInvalidReply("The model's reply was not valid JSON.")
        assert client.post("/api/llm/test", json={}).json()["error"].endswith("valid JSON.")


def test_the_test_route_without_a_key(tmp_path: Path) -> None:
    factory = Factory()
    with client_for(tmp_path, factory) as client:
        body = client.post("/api/llm/test", json={"preset": "deepseek"}).json()
    assert body == {"ok": False, "error": "No API key is set for DeepSeek."}
    assert factory.built == []


def test_the_test_route_overrides_the_saved_values(tmp_path: Path) -> None:
    factory = Factory({"ok": True})
    with client_for(tmp_path, factory, preset="deepseek") as client:
        client.put("/api/secrets/llm_api_key_groq", json={"value": KEY})
        body = client.post(
            "/api/llm/test",
            json={"preset": "groq", "model": "my-model", "base_url": "http://x.test/v1"},
        ).json()
        assert body["ok"] is True
        assert factory.built == [("groq", "my-model", "http://x.test/v1", KEY)]
        assert (
            client.get("/api/settings").json()["editable"]["llm"]["preset"] == "deepseek"
        )  # saved


@pytest.mark.parametrize(
    "body",
    [
        {"preset": "nope"},
        {"base_url": "ftp://x.test"},
        {"model": "m" * 201},
        {"enabled": True},
        {"model": 5},
    ],
)
def test_the_test_route_rejects_an_invalid_body(tmp_path: Path, body: dict[str, Any]) -> None:
    with client_for(tmp_path) as client:
        assert client.post("/api/llm/test", json=body).status_code == 422


# -- search -----------------------------------------------------------------------------------


def search(client: ApiClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/search", json={**QUERY, "limit": 5, **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_search_without_the_llm_has_null_fields(tmp_path: Path) -> None:
    factory = Factory()
    with client_for(tmp_path, factory) as client:
        data = search(client)
    assert data["llm"] is None and data["rerank"] is None
    assert data["parsed"]["source"] == "rules" and data["parsed"]["search_terms"] == []
    assert all(i["llm_rank"] is None and i["llm_explanation"] is None for i in data["items"])
    assert factory.provider.calls == []


def test_search_with_the_llm_parser(tmp_path: Path) -> None:
    reply = parse_reply(
        semantic_text="tense stealth level", search_terms=["stealth"], moods=["dark"]
    )
    factory = Factory(reply)
    with client_for(tmp_path, factory, **CUSTOM) as client:
        data = search(client, text="niveau d'infiltration tendu")
        assert data["parsed"]["source"] == "llm"
        assert data["parsed"]["search_terms"] == ["stealth"]
        assert data["parsed"]["semantic_text"] == "tense stealth level"
        assert data["llm"] == {"used": True, "model": "fake-model", "cached": False, "error": None}
        assert data["items"][0]["title"] in {"Shadow Walk", "Quiet Vents", "Night Heist"}
        again = search(client, text="niveau d'infiltration tendu", offset=2)
        assert again["llm"]["cached"] is True and len(factory.provider.calls) == 1
        assert ["tense stealth level"] in client.embedder.calls  # the English text was embedded


def test_a_failed_llm_parse_falls_back_with_a_note(tmp_path: Path) -> None:
    factory = Factory(LLMTimeout("Timed out after 10 s."))
    with client_for(tmp_path, factory, **CUSTOM) as client:
        data = search(client)
    assert data["items"] and data["parsed"]["source"] == "rules"
    assert data["llm"] == {
        "used": False,
        "model": "fake-model",
        "cached": False,
        "error": "Timed out after 10 s.",
    }
    assert "LLM: timed out after 10 s; used the rule parser." in data["parsed"]["notes"]


def test_enabled_without_a_key_reports_no_llm_block(tmp_path: Path) -> None:
    factory = Factory()
    with client_for(tmp_path, factory, enabled=True) as client:  # openai, no key saved
        data = search(client)
    assert data["llm"] is None and data["parsed"]["source"] == "rules"
    assert factory.built == []


def test_a_filter_only_search_has_no_llm_block(tmp_path: Path) -> None:
    factory = Factory()
    with client_for(tmp_path, factory, **CUSTOM) as client:
        data = client.post("/api/search", json={"filters": {"vocal": "vocal"}}).json()
    assert data["llm"] is None and factory.provider.calls == []


# -- rerank -----------------------------------------------------------------------------------


def test_rerank_reorders_and_shows_ratings(tmp_path: Path) -> None:
    factory = Factory(None)
    with client_for(tmp_path, factory, rerank_top_n=6, **CUSTOM) as client:
        plain = search(client, limit=6)  # the LLM parser asks first: an empty reply keeps rules
        titles = [i["title"] for i in plain["items"]]
        assert len(titles) == 6
        factory.provider.reply = rerank_reply(3, 1)
        client.put(
            "/api/ratings", json={**QUERY, "track_id": plain["items"][2]["track_id"], "rating": 2}
        )
        response = client.post("/api/search/rerank", json={**QUERY, "limit": 1, "offset": 9})
        assert response.status_code == 200, response.text
        data = response.json()
    assert [i["title"] for i in data["items"]] == [titles[n] for n in (2, 0, 1, 3, 4, 5)]
    assert [i["llm_rank"] for i in data["items"]] == [1, 2, 3, 4, 5, 6]
    assert (
        data["items"][0]["llm_explanation"] == "because 3"
        and data["items"][2]["llm_explanation"] is None
    )
    assert data["items"][0]["rating"] == 2 and data["items"][1]["rating"] is None
    assert data["items"][0]["explanation"]  # the template explanation is still there
    rerank = data["rerank"]
    assert {k: rerank[k] for k in ("model", "verdict", "summary", "search_terms")} == {
        "model": "fake-model",
        "verdict": "partial",
        "summary": "Meh.",
        "search_terms": ["x"],
    }
    assert rerank["elapsed_ms"] >= 0
    assert data["total_candidates"] >= 6 and data["parsed"]["source"] == "llm"
    call = factory.provider.calls[-1]
    assert call["name"] == "rerank" and call["timeout_s"] == 45


def test_rerank_needs_text(tmp_path: Path) -> None:
    with client_for(tmp_path, **CUSTOM) as client:
        for body in ({}, {"text": "   "}, {"filters": {"vocal": "vocal"}}):
            assert client.post("/api/search/rerank", json=body).status_code == 422


@pytest.mark.parametrize("llm", [{}, {"enabled": True}, {"enabled": True, "preset": "custom"}])
def test_rerank_is_a_503_when_the_llm_is_not_ready(tmp_path: Path, llm: dict[str, Any]) -> None:
    factory = Factory()
    with client_for(tmp_path, factory, **llm) as client:
        response = client.post("/api/search/rerank", json=QUERY)
    assert response.status_code == 503
    assert response.json() == {"detail": "No LLM is configured. Set one up in Settings."}
    assert factory.provider.calls == []


@pytest.mark.parametrize(
    "error",
    [
        LLMTimeout("Timed out after 45 s."),
        LLMAuthError("Authentication failed (HTTP 401). Check the API key."),
        LLMRateLimited("The LLM service is rate limiting requests (HTTP 429). Try again."),
        LLMInvalidReply("The model's reply was not valid JSON."),
    ],
)
def test_rerank_llm_failures_are_a_502_with_safe_text(tmp_path: Path, error: Exception) -> None:
    factory = Factory(parse_reply())
    with client_for(tmp_path, factory, **CUSTOM) as client:
        search(client)  # parse succeeds (cached afterwards)
        factory.provider.reply = error
        response = client.post("/api/search/rerank", json=QUERY)
    assert response.status_code == 502
    assert response.json() == {"detail": str(error)}


def test_rerank_search_errors_are_the_search_errors(tmp_path: Path) -> None:
    with client_for(tmp_path, **CUSTOM) as client:
        response = client.post(
            "/api/search/rerank", json={**QUERY, "filters": {"genres": ["nope"]}}
        )
    assert response.status_code == 422


# -- settings ---------------------------------------------------------------------------------


def test_settings_view_has_the_llm_section_and_presets(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        body = client.get("/api/settings").json()
    assert body["editable"]["llm"] == {
        "enabled": False,
        "preset": "openai",
        "model": "",
        "base_url": "",
        "parse_timeout_s": 10,
        "rerank_timeout_s": 45,
        "rerank_top_n": 20,
    }
    presets = body["llm_presets"]
    assert [p["id"] for p in presets][0] == "openai" and presets[-1]["id"] == "custom"
    assert presets[1] == {
        "id": "deepseek",
        "label": "DeepSeek",
        "kind": "openai",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-flash",
        "key_secret": "llm_api_key_deepseek",
        "key_required": True,
        "docs_url": "https://platform.deepseek.com/api_keys",
    }
    assert {p["id"]: p["kind"] for p in presets}["anthropic"] == "anthropic"
    assert presets[-1]["key_required"] is False
    assert get_preset("custom").default_model == presets[-1]["default_model"] == ""


def test_put_llm_settings_saves_and_the_search_parser_changes(tmp_path: Path) -> None:
    factory = Factory(parse_reply(semantic_text="tense stealth level"))
    with client_for(tmp_path, factory) as client:
        assert search(client)["llm"] is None
        response = client.put(
            "/api/settings", json={"llm": {**CUSTOM, "parse_timeout_s": 3, "rerank_top_n": 8}}
        )
        assert response.status_code == 200, response.text
        saved = response.json()["editable"]["llm"]
        assert (
            saved["enabled"] is True
            and saved["parse_timeout_s"] == 3
            and saved["rerank_top_n"] == 8
        )
        data = search(client)
        assert data["llm"]["used"] is True and data["parsed"]["source"] == "llm"
        assert factory.provider.calls[0]["timeout_s"] == 3
        client.put("/api/settings", json={"llm": {"enabled": False}})
        assert search(client)["llm"] is None
        assert client.get("/api/settings").json()["editable"]["llm"]["model"] == "fake-model"


@pytest.mark.parametrize(
    "llm",
    [
        {"preset": "nope"},
        {"base_url": "ftp://x"},
        {"base_url": "localhost:11434"},
        {"rerank_top_n": 4},
        {"rerank_top_n": 51},
        {"parse_timeout_s": 0},
        {"rerank_timeout_s": 121},
        {"unknown": 1},
    ],
)
def test_invalid_llm_settings_are_a_422_and_change_nothing(
    tmp_path: Path, llm: dict[str, Any]
) -> None:
    with client_for(tmp_path) as client:
        before = client.get("/api/settings").json()["editable"]["llm"]
        assert client.put("/api/settings", json={"llm": llm}).status_code == 422
        assert client.get("/api/settings").json()["editable"]["llm"] == before


def test_a_pinned_llm_field_is_a_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCRAR_LLM__MODEL", "from-env")
    with client_for(tmp_path) as client:
        assert "llm.model" in client.get("/api/settings").json()["overridden_by_env"]
        response = client.put("/api/settings", json={"llm": {"model": "x"}})
        assert response.status_code == 409 and "llm.model" in response.json()["detail"]
        assert client.put("/api/settings", json={"llm": {"enabled": True}}).status_code == 200


# -- the key stays on the server --------------------------------------------------------------


def test_the_key_never_appears_in_responses_or_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    factory = Factory(parse_reply(semantic_text="tense stealth level"))
    with client_for(tmp_path, factory, enabled=True) as client:
        client.put("/api/secrets/llm_api_key_openai", json={"value": KEY})
        texts = [
            client.get("/api/secrets").text,
            client.get("/api/llm").text,
            client.get("/api/settings").text,
            client.post("/api/llm/test").text,
            client.post("/api/search", json=QUERY).text,
            client.post("/api/search/rerank", json=QUERY).text,
        ]
        assert factory.built and all(call[3] == KEY for call in factory.built)  # it is used ...
    assert all(KEY not in text for text in texts)  # ... and never returned
    assert KEY not in caplog.text


# -- the import uses the LLM's keywords --------------------------------------------------------


def test_search_import_starts_with_the_llms_search_terms(tmp_path: Path) -> None:
    jamendo = IngestJamendo(2)
    factory = Factory(
        parse_reply(semantic_text="tense stealth level", search_terms=["stealth", "sneak"])
    )
    with make_client(
        tmp_path,
        jamendo=jamendo,
        llm_factory=factory,
        settings_overrides={"llm": CUSTOM},
    ) as client:
        response = client.post("/api/search/import", json={"text": "niveau furtif", "limit": 2})
        assert response.status_code == 202, response.text
        wait_done(client, response.json()["job"]["id"])
    assert jamendo.queries[0]["search"] == "stealth"
