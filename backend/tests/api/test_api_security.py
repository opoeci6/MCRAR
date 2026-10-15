"""Host and Origin checks, no CORS, and the error mapping."""

from __future__ import annotations

from pathlib import Path

import pytest
from api_support import make_client

from mcrar.api.security import allowed_hosts, is_loopback_origin
from mcrar.config import get_settings


def test_an_unknown_host_header_is_refused(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 400
        assert client.get("/api/health", headers={"Host": "evil.test:8000"}).status_code == 400
        for host in ("127.0.0.1:8000", "localhost:5173", "[::1]:8000", "testserver"):
            assert client.get("/api/health", headers={"Host": host}).status_code == 200, host


def test_testserver_is_not_a_default_host() -> None:
    assert "testserver" not in allowed_hosts(get_settings())
    assert {"127.0.0.1", "localhost", "[::1]"} <= set(allowed_hosts(get_settings()))


def test_the_configured_api_host_is_allowed_and_a_wildcard_bind_allows_any() -> None:
    assert "myhost.lan" in allowed_hosts(get_settings(api_host="myhost.lan"))
    assert "[fe80::1]" in allowed_hosts(get_settings(api_host="fe80::1"))
    assert allowed_hosts(get_settings(api_host="0.0.0.0")) == ["*"]


def test_state_changing_requests_need_a_loopback_origin(tmp_path: Path) -> None:
    body = {"text": "tense stealth level"}
    with make_client(tmp_path) as client:
        refused = client.post("/api/search", json=body, headers={"Origin": "https://evil.test"})
        assert refused.status_code == 403
        assert refused.json() == {"detail": "cross-origin request refused"}
        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "https://localhost",
            "http://[::1]:5173",
        ):
            ok = client.post("/api/search", json=body, headers={"Origin": origin})
            assert ok.status_code == 200, origin
        assert client.post("/api/search", json=body).status_code == 200  # no Origin: not a browser


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://localhost.evil.test",
        "http://evil.test:5173",
        "file://localhost/x",
        "ftp://127.0.0.1",
    ],
)
def test_lookalike_origins_are_refused(origin: str) -> None:
    assert not is_loopback_origin(origin)


def test_reads_are_allowed_from_any_origin_but_no_cors_headers_are_sent(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/health", headers={"Origin": "https://evil.test"})
        assert response.status_code == 200
        assert not any(h.lower().startswith("access-control") for h in response.headers)
        preflight = client.options(
            "/api/search",
            headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in preflight.headers


def test_errors_are_json_without_internals(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        missing = client.get("/api/tracks/99999")
        assert missing.status_code == 404 and missing.json() == {"detail": "no track with id 99999"}
        invalid = client.post("/api/search", json={})
        assert invalid.status_code == 422
        assert "Traceback" not in invalid.text
