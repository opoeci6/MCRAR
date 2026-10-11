"""SourceTrack + parsed licence -> the catalog's TrackRecord."""

from __future__ import annotations

from mcrar.catalog import TrackRecord
from mcrar.licensing import LicenseInfo, attribution_text
from mcrar.sources import SourceTrack


def to_track_record(
    src: SourceTrack, lic: LicenseInfo, *, attribution_extra: str | None = None
) -> TrackRecord:
    """Build the row for ``src`` with every licence column filled from ``lic``.

    ``license_url`` is the canonical URL of the parsed licence, else the raw URL the source gave
    (kept so an unrecognised licence can still be inspected).
    """
    return TrackRecord(
        source=src.source,
        source_id=src.source_id,
        title=src.title or None,
        artist=src.artist or None,
        album=src.album,
        duration_s=src.duration_s,
        release_date=src.release_date,
        source_url=src.source_url,
        stream_url=src.stream_url,
        download_url=src.download_url,
        audiodownload_allowed=src.audiodownload_allowed,
        image_url=src.image_url,
        local_path=src.local_path,
        license_url=lic.url or src.license_url,
        license_code=lic.code,
        license_family=lic.family,
        risk=lic.risk,
        commercial_ok=lic.commercial_ok,
        derivatives_ok=lic.derivatives_ok,
        share_alike=lic.share_alike,
        attribution_required=lic.attribution_required,
        attribution_text=attribution_text(
            title=src.title,
            artist=src.artist,
            license=lic,
            source_url=src.source_url,
            extra=attribution_extra,
        ),
        commercial_license_url=src.commercial_license_url,
        vocal_instrumental=src.vocal_instrumental,
        source_tags=dict(src.tags),
    )
