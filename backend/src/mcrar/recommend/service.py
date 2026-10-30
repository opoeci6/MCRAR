"""``SearchService``: parse, filter, retrieve, rank, explain; relax the filters when nothing fits.

Flow of one search
1. Parse the request (rules by default, or the LLM parser of M7 on top of them) into hard
   filters, soft preferences and the text to embed.
2. ``filter_track_ids`` applies the hard filters in SQL.
3. With text: embed it and take the ``pool_size`` nearest filtered tracks from the in-memory
   index. With a reference song (M10: a catalog track or an uploaded file, already embedded) do
   the same with its audio embedding; with both, the pool is the union of the two top lists and
   every pool track gets both cosines. The reference track itself is left out. Without text and
   reference: take the filtered tracks themselves (only the ``pool_size`` safest-licensed, unless
   a preference can rank them all).
4. Rank the pool (:mod:`mcrar.recommend.rank`), cap the tracks per artist, page, explain.
5. If fewer than ``search.min_results`` results remain, relax one hard filter at a time and
   search again: the duration bounds, then the BPM range (it becomes a soft target), then the
   vocal filter. The licence risk and the sources are never relaxed.

The text embedder is loaded on first use and kept; the vector index is cached and rebuilt when
the catalog's embeddings change. Torch is only imported when a text embedding is needed: a
filter-only genre/mood search is answered from the stored tags alone when every track in the pool
has them, and loads the text model (zero-shot scores) only for a pool track that lacks them.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import numpy as np

from mcrar.catalog import NumpyVectorIndex, StoredTrack
from mcrar.licensing import RISK_ORDER
from mcrar.recommend.explain import REFERENCE_BANDS, explain
from mcrar.recommend.parser import QueryParser, RuleParser
from mcrar.recommend.query import ParsedQuery, ReferenceQuery, SearchFilters, SearchRequest
from mcrar.recommend.rank import Candidate, Ranked, piece_key, rank_candidates
from mcrar.recommend.results import (
    LLMUse,
    MatchQuality,
    ReferenceInfo,
    SearchItem,
    SearchResult,
    TagScore,
)
from mcrar.recommend.tags import (
    CompositeTagScorer,
    StandardisedTagScorer,
    StoredTagScorer,
    TagScorer,
    ZeroShotTagScorer,
    allowed_tag_versions,
)
from mcrar.recommend.vocab import GENRE, MOODTHEME, SCENE, Vocabulary

if TYPE_CHECKING:
    from mcrar.catalog import CatalogRepository
    from mcrar.config import Settings

QUERY_CACHE_SIZE = 256
TOP_TAGS = 5
# Raw top-1 cosine under which a text search is "weak", per embedder key (overridden by
# ``search.weak_cosine``). CLAP on the owner's 1,054-track catalog: 15 rated game-music queries
# scored 0.41-0.66 with good results; clearly weak ones were "intense fight" 0.32, "anime
# opening" 0.37 and "bagpipes" 0.39. CLAP cannot tell J-pop from pop ("j-pop" 0.57, "japanese
# vocal" 0.47), so the UI offers the import for every text search, not only the weak ones.
# MuQ-MuLan does not separate cleanly either: it scores "j-pop" lowest of all (0.38, "anime
# opening" 0.40, "japanese vocal" 0.45), but 5 of 18 good queries also fall under 0.40 (as low
# as 0.32). The notice is only a suggestion, so 0.40 favours catching the weak ones. GLAP's
# cosines all sit near 0 (-0.07 to 0.11), so it has no threshold.
WEAK_COSINE_DEFAULTS = {"clap": 0.40, "muq-mulan": 0.40}
EmbedderLoader = Callable[[], Any]


class SearchError(ValueError):
    """A request that cannot be answered (bad arguments, a model that does not match the index)."""


def _default_loader(settings: Settings) -> Callable[[], Any]:
    def load() -> Any:
        from mcrar.ml.embedders import load_embedder

        return load_embedder(settings.default_embedder, settings=settings)

    return load


@dataclass
class _Outcome:
    """The ranked candidates of one attempt plus what is needed to build the items."""

    ranked: list[Ranked]
    pool_index: dict[int, int]
    tracks: dict[int, StoredTrack]
    features: dict[int, dict[str, Any]]
    tag_arrays: dict[tuple[str, str], np.ndarray]  # (label set, label) -> score per pool track
    top_sets: tuple[str, ...]
    unembedded: int
    top_cosine: float | None = None  # highest raw cosine of the ranked candidates (text only)
    ref_cosines: dict[int, float] = field(default_factory=dict)  # raw, per pool track


def _cosines(matrix: np.ndarray, vector: np.ndarray) -> list[float]:
    """Cosine of each unit row of ``matrix`` with ``vector`` (normalised here)."""
    unit = np.asarray(vector, dtype=np.float32)
    unit = unit / np.linalg.norm(unit)
    return [float(c) for c in matrix @ unit]


# -- relaxation ---------------------------------------------------------------------------------


def _fmt_range(low: float | None, high: float | None, unit: str = "") -> str:
    if low is not None and high is not None:
        return f"{low:g}-{high:g}{unit}"
    if high is not None:
        return f"≤ {high:g}{unit}"
    return f"≥ {low:g}{unit}"


def _relax_duration(q: ParsedQuery) -> tuple[ParsedQuery, str] | None:
    f = q.filters
    if f.duration_min_s is None and f.duration_max_s is None:
        return None
    note = f"Relaxed the duration limit ({_fmt_range(f.duration_min_s, f.duration_max_s, ' s')})"
    return replace(q, filters=replace(f, duration_min_s=None, duration_max_s=None)), note


def _relax_bpm(q: ParsedQuery) -> tuple[ParsedQuery, str] | None:
    f = q.filters
    if f.bpm_min is None and f.bpm_max is None:
        return None
    bounds = [b for b in (f.bpm_min, f.bpm_max) if b is not None]
    target = sum(bounds) / len(bounds)
    note = (
        f"Relaxed the BPM range ({_fmt_range(f.bpm_min, f.bpm_max)}) to a target of ~{target:g} BPM"
    )
    filters = replace(f, bpm_min=None, bpm_max=None)
    return replace(q, filters=filters, preferences=replace(q.preferences, bpm_target=target)), note


def _relax_vocal(q: ParsedQuery) -> tuple[ParsedQuery, str] | None:
    if q.filters.vocal is None:
        return None
    note = f"Relaxed the vocal filter ({q.filters.vocal} only)"
    return replace(q, filters=replace(q.filters, vocal=None)), note


RELAXATIONS = (_relax_duration, _relax_bpm, _relax_vocal)


def _empty_note(filters: SearchFilters) -> str:
    if filters.max_risk != "unknown":
        later = RISK_ORDER[RISK_ORDER.index(filters.max_risk) + 1]
        return f"No {filters.max_risk}-licence tracks match; try allowing {later}"
    if filters.sources:
        return f"No tracks match in {', '.join(filters.sources)}"
    return "No tracks match"


# -- the service --------------------------------------------------------------------------------


class SearchService:
    """Searches one catalog with the default embedding model.

    ``embedder_loader`` builds the text embedder on first use (default: ``load_embedder`` with
    ``settings.default_embedder``). ``tag_scorer`` replaces the built-in stored-then-zero-shot
    scoring. ``model_id`` is the embedding model searched; by default the registry's id of the
    default embedder, and a loaded embedder with another id is an error.

    ``stored_tags`` reads the tag rows of tracks. By default it only trusts the rows written by
    the selected tagging model (:func:`allowed_tag_versions`), so a track tagged by another
    version is scored zero-shot instead.
    Stored probabilities are standardised per label over the catalog
    (:class:`StandardisedTagScorer`) before they rank or explain, which puts them on the scale
    of the zero-shot scores.
    """

    def __init__(
        self,
        repo: CatalogRepository,
        settings: Settings,
        *,
        embedder_loader: EmbedderLoader | None = None,
        tag_scorer: TagScorer | None = None,
        stored_tags: StoredTagScorer | None = None,
        parser: QueryParser | None = None,
        vocab: Vocabulary | None = None,
        model_id: str | None = None,
    ) -> None:
        if model_id is None:
            from mcrar.ml import get_spec

            model_id = get_spec(settings.default_embedder).model_id
        self.model_id = model_id
        self._repo = repo
        self._settings = settings
        self._loader = embedder_loader or _default_loader(settings)
        self._custom_tags = tag_scorer
        self._parser = parser or RuleParser()
        self.vocab = vocab or Vocabulary.load(settings)
        self._lock = threading.RLock()
        self._embedder: Any = None
        self._index_cache: NumpyVectorIndex | None = None
        self._index_stats: tuple[int, str | None] | None = None
        self._queries: OrderedDict[str, np.ndarray] = OrderedDict()
        self._stored = stored_tags or StoredTagScorer(repo, allowed_tag_versions(settings))
        self._ranked_tags = StandardisedTagScorer(self._stored)
        self._tags_with_text = CompositeTagScorer(
            self._ranked_tags, ZeroShotTagScorer(self._index, self._embed_texts, self.vocab)
        )

    # -- lifecycle -------------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            embedder, self._embedder = self._embedder, None
        close = getattr(embedder, "close", None)
        if close is not None:
            close()

    # -- model and index -------------------------------------------------------------------

    @property
    def embedder_loaded(self) -> bool:
        return self._embedder is not None

    def _get_embedder(self) -> Any:
        with self._lock:
            if self._embedder is None:
                embedder = self._loader()
                if embedder.model_id != self.model_id:
                    raise SearchError(
                        f"the loaded embedder is {embedder.model_id}, "
                        f"but the catalog is searched with {self.model_id}"
                    )
                self._embedder = embedder
            return self._embedder

    def _embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        with self._lock:
            return np.asarray(self._get_embedder().embed_text(list(texts)), dtype=np.float32)

    def _embed_query(self, text: str) -> np.ndarray:
        # CLAP's text encoder is case-sensitive ("Tense ..." and "tense ..." ranked differently);
        # one intent should give one ranking, and ratings are keyed case-insensitively too.
        key = " ".join(text.split()).lower()
        with self._lock:
            cached = self._queries.get(key)
            if cached is not None:
                self._queries.move_to_end(key)
                return cached
            vector = self._embed_texts([key])[0]
            self._queries[key] = vector
            while len(self._queries) > QUERY_CACHE_SIZE:
                self._queries.popitem(last=False)
            return vector

    def _index(self) -> NumpyVectorIndex:
        """The vector index, rebuilt when the catalog's embeddings for the model changed."""
        with self._lock:
            stats = self._repo.embedding_stats(self.model_id)
            if self._index_cache is None or stats != self._index_stats:
                self._index_cache = NumpyVectorIndex.from_repository(self._repo, self.model_id)
                self._index_stats = stats
            return self._index_cache

    # -- search ----------------------------------------------------------------------------

    def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        if request.limit < 1 or request.offset < 0:
            raise SearchError("limit must be at least 1 and offset must not be negative")
        parsed, llm_use = self._parse(request)
        self._check_labels(parsed)
        min_results = self._settings.search.min_results

        reference = request.reference
        attempt, relaxed = parsed, []
        outcome = self._execute(attempt, reference)
        for relax in RELAXATIONS:
            if len(outcome.ranked) >= min_results:
                break
            step = relax(attempt)
            if step is None:
                continue
            attempt, note = step
            relaxed.append(note)
            outcome = self._execute(attempt, reference)

        notes: list[str] = []
        if outcome.unembedded:
            by = "text search" if parsed.semantic_text or reference is None else "reference search"
            notes.append(
                f"{outcome.unembedded} matching track(s) have no {self.model_id} embedding, so "
                f"{by} cannot find them; run: mcrar embed"
            )
        if not outcome.ranked:
            notes.append(_empty_note(attempt.filters))
        page = outcome.ranked[request.offset : request.offset + request.limit]
        items = [self._item(r, outcome, attempt, request.explain, reference) for r in page]
        return SearchResult(
            items=items,
            total_candidates=len(outcome.ranked),
            parsed=parsed,
            relaxed=relaxed,
            unembedded_count=outcome.unembedded,
            model_id=self.model_id,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            notes=notes,
            match=self._match(attempt, outcome),
            llm=llm_use,
            reference=None
            if reference is None
            else ReferenceInfo(
                reference.kind, reference.track_id, reference.label, reference.weight
            ),
        )

    def reference_for_track(self, track_id: int, weight: float = 0.5) -> ReferenceQuery:
        """A catalog track as the reference song of a search, with its stored embedding.

        Raises ``LookupError`` for an unknown track and :class:`SearchError` for a track that has
        no embedding yet for the model searched. ``weight`` is the reference's share (0 to 1)."""
        track = self._repo.get_track(track_id)
        if track is None:
            raise LookupError(f"no track with id {track_id}")
        label = track.title or "(untitled)"
        if track.artist:
            label += f" — {track.artist}"
        vector = self._repo.get_embedding(track_id, self.model_id)
        if vector is None:
            raise SearchError(
                f'"{label}" has no {self.model_id} embedding yet, so it cannot be a reference '
                'song; use "Re-embed missing tracks" in Settings, or run: mcrar embed'
            )
        return ReferenceQuery(vector, label, "track", track_id, weight)

    def _parse(self, request: SearchRequest) -> tuple[ParsedQuery, LLMUse | None]:
        """Parse with the parser's ``parse_with_info`` when it has one (the LLM parser: what it
        did comes back with the result, so concurrent searches share no state)."""
        with_info = getattr(self._parser, "parse_with_info", None)
        if with_info is not None:
            return with_info(request, self.vocab)
        return self._parser.parse(request, self.vocab), None

    def parse(self, request: SearchRequest) -> ParsedQuery:
        """The request as the search understands it (no retrieval, no search model)."""
        return self._parse(request)[0]

    def weak_cosine(self) -> float | None:
        """The weak-match threshold: ``search.weak_cosine``, else the default of the embedder
        this service searches with; None when neither is known (nothing is then weak)."""
        configured = self._settings.search.weak_cosine
        if configured is not None:
            return configured
        key = self._embedder_key()
        return WEAK_COSINE_DEFAULTS.get(key) if key is not None else None

    def _embedder_key(self) -> str | None:
        """The registry key (``clap``, ...) of the model this service searches with, if known."""
        from mcrar.ml import MODELS

        return next((k for k, spec in MODELS.items() if spec.model_id == self.model_id), None)

    def _match(self, attempt: ParsedQuery, outcome: _Outcome) -> MatchQuality:
        if not attempt.semantic_text:
            return MatchQuality()
        threshold = self.weak_cosine()
        top = outcome.top_cosine
        weak = threshold is not None and (top is None or top < threshold)
        return MatchQuality(top_cosine=top, weak=weak)

    def _check_labels(self, parsed: ParsedQuery) -> None:
        for label_set, label in parsed.requested_labels():
            if not self.vocab.has(label_set, label):
                raise SearchError(f"unknown {label_set} label '{label}'")

    def _scorer(self, parsed: ParsedQuery, requested: list[tuple[str, str]]) -> TagScorer:
        """Zero-shot tag scoring needs the text model: use it when the search loads it anyway
        (a text query, requested labels) or it is already loaded; else only stored tags. Both
        are standardised per label over the catalog, so ranking and top tags share one scale."""
        if self._custom_tags is not None:
            return self._custom_tags
        if parsed.semantic_text or requested or self.embedder_loaded:
            return self._tags_with_text
        return self._ranked_tags

    def _execute(self, q: ParsedQuery, reference: ReferenceQuery | None = None) -> _Outcome:
        f, prefs = q.filters, q.preferences
        cfg = self._settings.search
        ids = self._repo.filter_track_ids(
            max_risk=f.max_risk,
            vocal=f.vocal,
            bpm_min=f.bpm_min,
            bpm_max=f.bpm_max,
            duration_min_s=f.duration_min_s,
            duration_max_s=f.duration_max_s,
            sources=f.sources,
        )
        if not ids:  # nothing can match: no index, no query embedding, so no model load either
            return _Outcome(
                ranked=[],
                pool_index={},
                tracks={},
                features={},
                tag_arrays={},
                top_sets=(),
                unembedded=0,
            )
        index = self._index()
        unembedded = int(len(ids) - np.isin(np.asarray(ids, dtype=np.int64), index.ids).sum())

        requested = q.requested_labels()
        cosines: dict[int, float] = {}
        ref_cosines: dict[int, float] = {}
        if q.semantic_text or reference is not None:
            # the reference track is not its own best match
            allowed = [i for i in ids if reference is None or i != reference.track_id]
            text_vector = self._embed_query(q.semantic_text) if q.semantic_text else None
            text_hits: list[tuple[int, float]] = []
            ref_hits: list[tuple[int, float]] = []
            if text_vector is not None:
                try:
                    text_hits = index.search(text_vector, k=cfg.pool_size, allowed_ids=allowed)
                except ValueError as exc:
                    raise SearchError(
                        f"the query embedding does not fit the index: {exc}"
                    ) from None
            if reference is not None:
                try:
                    ref_hits = index.search(reference.vector, k=cfg.pool_size, allowed_ids=allowed)
                except ValueError as exc:
                    raise SearchError(
                        f"the reference song's embedding does not fit the index: {exc}"
                    ) from None
            pool = list(dict.fromkeys(track_id for track_id, _ in (*text_hits, *ref_hits)))
            if text_vector is not None and reference is not None:
                # Both lists feed the pool, so every pool track needs both cosines.
                if pool:
                    _, matrix = index.vectors(pool)  # every pool track is indexed
                    cosines = dict(zip(pool, _cosines(matrix, text_vector), strict=True))
                    ref_cosines = dict(zip(pool, _cosines(matrix, reference.vector), strict=True))
            elif text_vector is not None:
                cosines = dict(text_hits)
            else:
                ref_cosines = dict(ref_hits)
        else:
            # Without text only preferences can tell tracks apart; then rank them all.
            has_preference = bool(requested) or prefs.bpm_target is not None
            has_preference = has_preference or prefs.energy_target is not None
            if has_preference:
                pool = ids
            else:  # nothing to rank by: keep the safest-licensed tracks (then lowest ids)
                risks = {i: t.risk for i, t in self._repo.get_tracks(ids).items()}
                safest = sorted(risks, key=lambda i: (RISK_ORDER.index(risks[i]), i))
                pool = safest[: cfg.pool_size]

        tracks = self._repo.get_tracks(pool)
        features = self._repo.get_features_many(pool)
        pieces = {i: piece_key(t.title, t.artist, t.duration_s) for i, t in tracks.items()}
        pool = [i for i in pool if i in tracks]
        if reference is not None and reference.track_id is not None:
            # another copy of the reference song is not a match either
            source = self._repo.get_track(reference.track_id)
            own = piece_key(source.title, source.artist, source.duration_s) if source else None
            if own is not None:
                pool = [i for i in pool if pieces[i] != own]

        top_sets = tuple(dict.fromkeys(label_set for label_set, _ in requested)) or (
            GENRE,
            MOODTHEME,
            SCENE,
        )
        tag_arrays: dict[tuple[str, str], np.ndarray] = {}
        if pool:
            scorer = self._scorer(q, requested)
            for label_set in top_sets:
                labels = self.vocab.labels(label_set)
                for label, values in scorer.scores(pool, label_set, labels).items():
                    tag_arrays[(label_set, label)] = np.asarray(values, dtype=np.float64)

        candidates = []
        for i, track_id in enumerate(pool):
            feats = features.get(track_id) or {}
            candidates.append(
                Candidate(
                    track_id=track_id,
                    artist=tracks[track_id].artist,
                    risk=tracks[track_id].risk,
                    cosine=cosines.get(track_id),
                    ref_cosine=ref_cosines.get(track_id),
                    bpm=feats.get("bpm"),
                    bpm_confidence=feats.get("bpm_confidence"),
                    energy=feats.get("energy"),
                    tags=tuple(float(tag_arrays[key][i]) for key in requested),
                    same_piece=pieces[track_id],
                )
            )
        ranked = rank_candidates(
            candidates,
            weights=cfg.weights,
            semantic=bool(q.semantic_text),
            tags=bool(requested),
            reference=reference is not None,
            reference_weight=reference.weight if reference is not None else 0.5,
            bpm_target=prefs.bpm_target,
            energy_target=prefs.energy_target,
            max_per_artist=cfg.max_per_artist,
        )
        return _Outcome(
            ranked=ranked,
            pool_index={track_id: i for i, track_id in enumerate(pool)},
            tracks=tracks,
            features=features,
            tag_arrays=tag_arrays,
            top_sets=top_sets,
            unembedded=unembedded,
            top_cosine=max((float(cosines[r.track_id]) for r in ranked), default=None)
            if q.semantic_text
            else None,
            ref_cosines=ref_cosines,
        )

    def _item(
        self,
        ranked: Ranked,
        outcome: _Outcome,
        q: ParsedQuery,
        with_explanation: bool,
        reference: ReferenceQuery | None = None,
    ):
        track = outcome.tracks[ranked.track_id]
        feats = outcome.features.get(ranked.track_id) or {}
        i = outcome.pool_index[ranked.track_id]
        top = [
            TagScore(label_set, label, self.vocab.display_name(label_set, label), float(v[i]))
            for (label_set, label), v in outcome.tag_arrays.items()
            if label_set in outcome.top_sets and v[i] > 0.0
        ]
        top.sort(key=lambda t: (-t.score, t.label_set, t.label))
        asked = [
            (label, float(outcome.tag_arrays[(label_set, label)][i]))
            for label_set, label in q.requested_labels()
        ]
        similar = None
        if reference is not None and ranked.track_id in outcome.ref_cosines:
            similar = (reference.label, outcome.ref_cosines[ranked.track_id])
        bands = REFERENCE_BANDS.get(self._embedder_key() or "") if similar else None
        return SearchItem(
            track_id=track.id,
            title=track.title,
            artist=track.artist,
            source=track.source,
            source_url=track.source_url,
            download_url=track.download_url if track.audiodownload_allowed else None,
            duration_s=track.duration_s,
            bpm=feats.get("bpm"),
            bpm_confidence=feats.get("bpm_confidence"),
            key=feats.get("key"),
            mode=feats.get("mode"),
            energy=feats.get("energy"),
            license_code=track.license_code,
            risk=track.risk,
            license_url=track.license_url,
            attribution_text=track.attribution_text,
            commercial_license_url=track.commercial_license_url,
            top_tags=top[:TOP_TAGS],
            score=ranked.score,
            breakdown=ranked.breakdown.to_dict(),
            explanation=(
                explain(track, feats, ranked.breakdown, q, asked, similar, bands)
                if with_explanation
                else None
            ),
        )
