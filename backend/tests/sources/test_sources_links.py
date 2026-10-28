"""parse_track_links: the Jamendo and Freesound ids in pasted text (no network)."""

from __future__ import annotations

import pytest

from mcrar.sources.links import MAX_LINKS, parse_track_links


@pytest.mark.parametrize(
    "link",
    [
        "https://www.jamendo.com/track/1234",
        "https://www.jamendo.com/track/1234/some-slug",
        "https://www.jamendo.com/track/1234/some-slug/",
        "http://jamendo.com/track/1234",
        "https://jamendo.com/track/1234/",
        "https://www.jamendo.com/en/track/1234/some-slug",
        "https://www.jamendo.com/fr/track/1234",
        "https://www.jamendo.com/track/1234?language=en#comments",
        "https://www.jamendo.com/track/1234/slug?utm_source=x",
        "HTTPS://WWW.JAMENDO.COM/track/1234",
        "jamendo.com/track/1234",
        "https://licensing.jamendo.com/track/1234",
        "https://licensing.jamendo.com/en/track/1234",
        "https://licensing.jamendo.com/en/track/1234/slug",
        "https://jamen.do/t/1234",
        "http://jamen.do/t/1234/",
        "jamendo:1234",
        "Jamendo:1234",
    ],
)
def test_jamendo_shapes(link: str) -> None:
    found = parse_track_links(link)
    assert (found.jamendo, found.freesound, found.invalid) == (["1234"], [], [])


@pytest.mark.parametrize(
    "link",
    [
        "https://freesound.org/people/some_user/sounds/5678/",
        "https://freesound.org/people/some_user/sounds/5678",
        "https://www.freesound.org/people/Some.User-1/sounds/5678/",
        "http://freesound.org/people/u/sounds/5678/?page=2#comments",
        "https://freesound.org/s/5678/",
        "https://freesound.org/s/5678",
        "FREESOUND.ORG/s/5678",
        "freesound:5678",
        "FreeSound:5678",
    ],
)
def test_freesound_shapes(link: str) -> None:
    found = parse_track_links(link)
    assert (found.jamendo, found.freesound, found.invalid) == ([], ["5678"], [])


def test_entries_may_be_separated_by_newlines_commas_and_spaces() -> None:
    text = (
        "https://www.jamendo.com/track/1/a\n"
        "jamendo:2, freesound:3,freesound:4 ,\n\n"
        "  https://freesound.org/s/5/\t https://jamen.do/t/6  "
    )
    found = parse_track_links(text)
    assert found.jamendo == ["1", "2", "6"]
    assert found.freesound == ["3", "4", "5"]
    assert found.invalid == []


def test_duplicates_are_dropped_keeping_the_first_position() -> None:
    text = (
        "jamendo:2 jamendo:1 https://www.jamendo.com/track/2/x jamendo:002 "
        "junk junk freesound:9 freesound:9"
    )
    found = parse_track_links(text)
    assert found.jamendo == ["2", "1"]
    assert found.freesound == ["9"]
    assert found.invalid == ["junk"]


def test_the_same_id_on_two_sources_is_two_tracks() -> None:
    found = parse_track_links("jamendo:7 freesound:7")
    assert (found.jamendo, found.freesound) == (["7"], ["7"])


@pytest.mark.parametrize(
    "entry",
    [
        "hello",
        "https://example.com/track/1234",
        "https://www.jamendo.com/",
        "https://www.jamendo.com/artist/1234",
        "https://www.jamendo.com/album/1234",
        "https://www.jamendo.com/track/",
        "https://www.jamendo.com/track/abc",
        "https://www.jamendo.com/track/12a4",
        "https://www.jamendo.com/track/-5",
        "https://www.jamendo.com/track/1234/slug/extra",
        "https://www.jamendo.com/english/track/1234",
        "https://jamen.do/x/1234",
        "https://jamen.do/t/abc",
        "https://freesound.org/people/u/sounds/abc/",
        "https://freesound.org/people/u/sounds/",
        "https://freesound.org/people/u/1234/",
        "https://freesound.org/browse/tags/x/",
        "ftp://freesound.org/s/1234/",
        "javascript:alert(1)",
        "jamendo:abc",
        "jamendo:",
        "freesound:12.5",
        "spotify:1234",
        "١٢٣",  # Arabic-Indic digits are not ids
        "jamendo:١٢",
    ],
)
def test_other_entries_are_invalid(entry: str) -> None:
    found = parse_track_links(entry)
    assert (found.jamendo, found.freesound) == ([], [])
    assert found.invalid == [entry]


@pytest.mark.parametrize(
    "entry",
    [
        "https://jamendo.com.evil.test/track/1234",
        "https://evil.test/jamendo.com/track/1234",
        "https://evil.test/?u=https://jamendo.com/track/1234",
        "https://notjamendo.com/track/1234",
        "https://eviljamendo.com/track/1234",
        "https://jamendo.com@evil.test/track/1234",
        "https://www.jamendo.com@evil.test/track/1234",
        "https://user@jamendo.com/track/1234",
        "https://jamendo.com:8080/track/1234",
        "https://sub.jamendo.com/track/1234",
        "https://jamen.do.evil.test/t/1234",
        "https://evilfreesound.org/s/1234/",
        "https://freesound.org.evil.test/s/1234/",
        "https://freesound.org@evil.test/s/1234/",
        "https://cdn.freesound.org/s/1234/",
        "https://wwwfreesound.org/s/1234/",
        "https://www.www.freesound.org/s/1234/",
        "https://freesound.org.evil.test/people/u/sounds/1234/",
    ],
)
def test_look_alike_hosts_are_invalid(entry: str) -> None:
    found = parse_track_links(entry)
    assert (found.jamendo, found.freesound) == ([], [])
    assert found.invalid == [entry]


def test_valid_and_invalid_entries_are_sorted_apart() -> None:
    found = parse_track_links("jamendo:1 nope https://freesound.org/s/2/ http://x.test/a")
    assert found.jamendo == ["1"] and found.freesound == ["2"]
    assert found.invalid == ["nope", "http://x.test/a"]


def test_empty_text_finds_nothing() -> None:
    found = parse_track_links(" \n , ,\t")
    assert (found.jamendo, found.freesound, found.invalid) == ([], [], [])


def test_the_limit_is_fifty_valid_ids_in_all() -> None:
    assert MAX_LINKS == 50
    ok = (
        " ".join(f"jamendo:{n}" for n in range(30))
        + " "
        + " ".join(f"freesound:{n}" for n in range(20))
    )
    assert len(parse_track_links(ok).jamendo) + len(parse_track_links(ok).freesound) == 50
    with pytest.raises(ValueError, match="at most 50"):
        parse_track_links(ok + " freesound:99")


def test_the_limit_counts_distinct_ids_only() -> None:
    text = " ".join(f"jamendo:{n % 50}" for n in range(200)) + " junk" * 80
    found = parse_track_links(text)
    assert len(found.jamendo) == 50 and found.invalid == ["junk"]


def test_the_result_is_frozen() -> None:
    found = parse_track_links("jamendo:1")
    with pytest.raises(AttributeError):
        found.jamendo = []  # type: ignore[misc]
