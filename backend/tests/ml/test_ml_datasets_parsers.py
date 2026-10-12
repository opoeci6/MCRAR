"""Publisher-shaped metadata fixtures cover split membership, labels and scale mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcrar.ml.datasets import parse_deam, parse_fma, parse_mtg


def test_fma_two_headers_medium_membership_and_split(tmp_path: Path) -> None:
    path = tmp_path / "tracks.csv"
    path.write_text(
        ",set,set,track\n,subset,split,genre_top\ntrack_id,,,\n"
        "2,small,training,Hip-Hop\n1001,medium,validation,Old-Time / Historic\n"
        "2001,large,test,Rock\n3001,medium,test,Jazz\n",
        encoding="utf-8",
    )
    samples = parse_fma(path, tmp_path)
    assert [s.id for s in samples] == [2, 1001, 3001]
    assert [s.split for s in samples] == ["train", "validation", "test"]
    assert samples[1].targets == {"genre": ("old-time-historic",)}
    assert samples[1].path == tmp_path / "001/001001.mp3"


def test_mtg_real_id_prefix_and_tag_prefix(tmp_path: Path) -> None:
    for i, split in enumerate(("train", "validation", "test")):
        (tmp_path / f"autotagging_moodtheme-{split}.tsv").write_text(
            "TRACK_ID\tARTIST_ID\tALBUM_ID\tPATH\tDURATION\tTAGS\n"
            f"track_{i:07d}\tartist_0001\talbum_0001\t00/{i}.mp3\t90\t"
            "mood/theme---happy\tmood/theme---deep\n",
            encoding="utf-8",
        )
    samples = parse_mtg(tmp_path, tmp_path / "audio")
    assert [s.split for s in samples] == ["train", "validation", "test"]
    assert samples[0].targets == {"moodtheme": ("happy", "deep")}
    assert samples[0].path == tmp_path / "audio/00/0.low.mp3"
    (tmp_path / "autotagging_moodtheme-test.tsv").write_text(
        "track_0000000\tartist_1\talbum_1\t00/0.mp3\t90\tmood/theme---happy\n"
    )
    with pytest.raises(ValueError, match="more than one split"):
        parse_mtg(tmp_path, tmp_path)


def test_deam_scale_and_reproducible_id_split(tmp_path: Path) -> None:
    path = tmp_path / "song_level.csv"
    path.write_text(
        "song_id, valence_mean, arousal_mean\n"
        + "".join(f"{i}, {1 + i % 9}, {9 - i % 9}\n" for i in range(1, 21)),
        encoding="utf-8",
    )
    a, b = parse_deam([path], tmp_path), parse_deam([path], tmp_path)
    assert a == b
    assert [sum(s.split == split for s in a) for split in ("train", "validation", "test")] == [
        16,
        2,
        2,
    ]
    assert a[0].targets == {"valence": 0.125, "arousal": 0.875}
    path.write_text("song_id,valence_mean,arousal_mean\n1,10,5\n")
    with pytest.raises(ValueError, match="outside"):
        parse_deam([path], tmp_path)
