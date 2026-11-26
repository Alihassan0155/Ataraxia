"""Deterministic full-catalogue candidate generation; no final action selection."""
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
import math

import numpy as np

from .catalogue import Catalogue


def _integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in [{low}, {high}]')


@dataclass(frozen=True)
class RetrievalState:
    """Explicit input snapshot; watched_ids are chronological, oldest first.

    Replace this value after a preference/exposure change. Retrieval has no cache
    and does not itself advance state or learn preferences.
    """
    interest_vector: tuple[float, ...]
    watched_ids: tuple[str, ...] = ()

    def __post_init__(self):
        vector = np.asarray(self.interest_vector, dtype=np.float64)
        norm = np.linalg.norm(vector)
        if vector.ndim != 1 or not np.isfinite(vector).all() or not math.isfinite(norm) or norm < 1e-12:
            raise ValueError('interest_vector must be a finite, nonzero 1D vector')
        object.__setattr__(self, 'interest_vector', tuple(float(x) for x in vector))
        history = tuple(self.watched_ids)
        if any(not isinstance(x, str) or not x for x in history):
            raise ValueError('watched_ids must contain nonempty strings')
        object.__setattr__(self, 'watched_ids', history)


@dataclass(frozen=True)
class RetrievalConfig:
    main_k: int = 20
    alternative_k: int = 20
    history_rule: str = 'all'   # all, recent, none
    history_window: int = 20   # last N exposure events, including repeats
    min_relevance: float = 0.30
    max_relevance_drop: float = 0.15
    min_semantic_distance: float = 0.10
    min_recovery: float = 0.60
    recovery_margin: float = 0.05
    outside_main_only: bool = True

    def __post_init__(self):
        for name in ('main_k', 'alternative_k', 'history_window'):
            _integer(getattr(self, name), name)
        if self.history_rule not in ('all', 'recent', 'none'):
            raise ValueError('history_rule must be all, recent or none')
        for name, low, high in [('min_relevance', -1, 1), ('max_relevance_drop', 0, 2),
                                ('min_semantic_distance', 0, 2), ('min_recovery', 0, 1),
                                ('recovery_margin', 0, 1)]:
            _number(getattr(self, name), name, low, high)
        if not isinstance(self.outside_main_only, bool):
            raise ValueError('outside_main_only must be bool')


@dataclass(frozen=True)
class AffectFeatures:
    valence: float
    arousal: float
    recovery_suitability: float
    confidence: float
    emotions: tuple[float, ...]  # order: catalogue.EMOTIONS
    dominant_emotion: str


@dataclass(frozen=True)
class StrategyEligibility:
    main_pool: bool
    meets_relevance_floor: bool
    diverse: bool
    recovery: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    video_id: str
    category: str
    relevance: float
    relevance_rank: int  # rank among currently unexcluded videos
    affect: AffectFeatures
    eligibility: StrategyEligibility
    outside_main: bool
    semantic_distance: float  # 1 - max cosine to the current main pool
    recovery_gain: float       # relative to mean main-pool recovery


@dataclass(frozen=True)
class RetrievalResult:
    search: str
    candidates: tuple[Candidate, ...]
    status: str
    reason: str | None
    catalogue_size: int
    available_count: int
    excluded_history_count: int
    qualifying_count: int
    requested_k: int
    relevance_floor: float
    recovery_baseline: float | None
    config: RetrievalConfig


class CandidateRetriever:
    def __init__(self, catalogue: Catalogue, config: RetrievalConfig | None = None):
        self.catalogue = catalogue
        self.config = config or RetrievalConfig()
        self._matrix = np.array(catalogue.embeddings, dtype=np.float64, copy=True)
        ids = [r.video_id for r in catalogue.records]
        if self._matrix.shape != (len(ids), 1024) or len(ids) != len(set(ids)):
            raise ValueError('catalogue must contain unique IDs and aligned 1024D rows')
        if ids != catalogue.video_ids.tolist() or any(catalogue.id_to_row.get(v) != i for i, v in enumerate(ids)):
            raise ValueError('catalogue ID-to-vector alignment mismatch')
        if not np.isfinite(self._matrix).all() or not np.allclose(np.linalg.norm(self._matrix, axis=1), 1, atol=1e-4, rtol=0):
            raise ValueError('catalogue vectors must be finite and unit normalized')
        self._matrix.setflags(write=False)
        self._ids = tuple(ids)
        self._rows = dict(catalogue.id_to_row)
        self._categories = {}
        for i, record in enumerate(catalogue.records):
            self._categories.setdefault(record.category, []).append(i)

    def initialize_state(self, categories: Sequence[str] | Mapping[str, float], *, watched_ids=()):
        """Normalized weighted sum of unit category centroids (equal weights by default)."""
        if isinstance(categories, (str, bytes)):
            raise ValueError('pass a category sequence or category-to-weight mapping')
        if isinstance(categories, Mapping):
            weights = dict(categories)
        else:
            names = list(categories)
            if len(names) != len(set(names)):
                raise ValueError('selected categories must be unique')
            weights = dict.fromkeys(names, 1.0)
        if not weights:
            raise ValueError('select at least one category')
        vector = np.zeros(1024, dtype=np.float64)
        for category in sorted(weights):
            if category not in self._categories:
                raise ValueError(f'category absent from eligible catalogue: {category}')
            weight = weights[category]
            _number(weight, 'category weight', 0, 1e12)
            centroid = self._matrix[self._categories[category]].mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm < 1e-12:
                raise ValueError(f'undefined category centroid: {category}')
            vector += weight * centroid / norm
        norm = np.linalg.norm(vector)
        if norm < 1e-12:
            raise ValueError('weighted category centroids must have a nonzero sum')
        return RetrievalState(tuple(vector / norm), tuple(watched_ids))

    def retrieve_relevant(self, state: RetrievalState, k: int | None = None):
        return self._retrieve(state, 'relevant', k)

    def retrieve_diverse_alternatives(self, state: RetrievalState, k: int | None = None):
        return self._retrieve(state, 'diverse', k)

    def retrieve_recovery_alternatives(self, state: RetrievalState, k: int | None = None):
        return self._retrieve(state, 'recovery', k)

    def _retrieve(self, state, search, k):
        config = self.config
        k = (config.main_k if search == 'relevant' else config.alternative_k) if k is None else k
        _integer(k, 'k')
        interest = np.array(state.interest_vector, dtype=np.float64)
        if interest.shape != (1024,):
            raise ValueError('interest vector dimension must match catalogue (1024)')
        interest /= np.linalg.norm(interest)
        unknown = set(state.watched_ids) - self._rows.keys()
        if unknown:
            raise ValueError('history contains IDs outside the eligible catalogue')
        history = state.watched_ids
        excluded = (set(history) if config.history_rule == 'all' else
                    set(history[-config.history_window:]) if config.history_rule == 'recent' else set())
        # Scores always cover the entire catalogue. History is applied before ranking.
        scores = np.clip(self._matrix @ interest, -1, 1)
        order = sorted((i for i, vid in enumerate(self._ids) if vid not in excluded),
                       key=lambda i: (-float(scores[i]), self._ids[i]))
        main_size = k if search == 'relevant' else config.main_k
        main = order[:main_size]
        main_set = set(main)
        floor = max(config.min_relevance, float(scores[order[0]]) - config.max_relevance_drop) if order else config.min_relevance
        baseline = float(np.mean([self.catalogue.records[i].recovery_suitability for i in main])) if main else None
        if main:
            distance = 1 - np.clip((self._matrix @ self._matrix[main].T).max(axis=1), -1, 1)
        else:
            distance = np.zeros(len(self._ids))
        qualifying = []
        for rank, i in enumerate(order, 1):
            record = self.catalogue.records[i]
            outside = i not in main_set
            relevant = float(scores[i]) >= floor
            scope = outside or not config.outside_main_only
            gain = record.recovery_suitability - baseline
            diverse = relevant and scope and float(distance[i]) >= config.min_semantic_distance
            recovery = relevant and scope and record.recovery_suitability >= config.min_recovery and gain > config.recovery_margin
            reasons = []
            if not relevant:
                reasons.append('below_relevance_floor')
            if not scope:
                reasons.append('inside_main_pool')
            if float(distance[i]) < config.min_semantic_distance:
                reasons.append('too_similar_to_main_pool')
            if record.recovery_suitability < config.min_recovery:
                reasons.append('below_recovery_floor')
            if gain <= config.recovery_margin:
                reasons.append('insufficient_recovery_gain')
            eligible = StrategyEligibility(i in main_set, relevant, diverse, recovery, tuple(reasons))
            if (search == 'relevant' and i in main_set) or (search == 'diverse' and diverse) or (search == 'recovery' and recovery):
                qualifying.append(Candidate(record.video_id, record.category, float(scores[i]), rank,
                                            AffectFeatures(record.valence, record.arousal, record.recovery_suitability,
                                                           record.confidence, record.emotions, record.dominant_emotion),
                                            eligible, outside, float(distance[i]), float(gain)))
        if search == 'diverse':
            qualifying.sort(key=lambda c: (-c.semantic_distance, -c.relevance, c.video_id))
        elif search == 'recovery':
            qualifying.sort(key=lambda c: (-c.affect.recovery_suitability, -c.relevance, c.video_id))
        # Never pad shortages or relax thresholds silently.
        reason = ('history_exhausted_catalogue' if not order and self._ids else
                  'empty_catalogue' if not self._ids else 'no_qualifying_alternative') if not qualifying else None
        return RetrievalResult(search, tuple(qualifying[:k]), 'ok' if qualifying else 'empty', reason,
                               len(self._ids), len(order), len(excluded), len(qualifying), k, floor, baseline, config)
