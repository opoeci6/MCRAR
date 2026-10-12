"""Search and ranking: query parsing, retrieval, weighted ranking and explanations.

Importing this package never imports torch; the text model is loaded by
:class:`SearchService` on the first text query.
"""

from mcrar.recommend.parser import QueryParser, RuleParser, parse
from mcrar.recommend.query import ParsedQuery, Preferences, SearchFilters, SearchRequest
from mcrar.recommend.rank import ScoreBreakdown, TermScore
from mcrar.recommend.results import SearchItem, SearchResult, TagScore
from mcrar.recommend.service import SearchError, SearchService
from mcrar.recommend.tags import CompositeTagScorer, StoredTagScorer, TagScorer, ZeroShotTagScorer
from mcrar.recommend.vocab import Vocabulary

__all__ = [
    "CompositeTagScorer",
    "ParsedQuery",
    "Preferences",
    "QueryParser",
    "RuleParser",
    "ScoreBreakdown",
    "SearchError",
    "SearchFilters",
    "SearchItem",
    "SearchRequest",
    "SearchResult",
    "SearchService",
    "StoredTagScorer",
    "TagScore",
    "TagScorer",
    "TermScore",
    "Vocabulary",
    "ZeroShotTagScorer",
    "parse",
]
