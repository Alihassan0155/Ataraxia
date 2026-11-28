"""Unified research retrieval using the Stage 2 scoring and eligibility rules."""
from dataclasses import dataclass
from itertools import combinations

from .catalogue import Catalogue
from .retrieval import CandidateRetriever, RetrievalConfig, RetrievalResult, RetrievalState

POOL_ORDER = ('Current', 'Stable', 'Recovery', 'Diverse')


@dataclass(frozen=True)
class FourPoolResult:
    current: RetrievalResult
    stable: RetrievalResult
    recovery: RetrievalResult
    diverse: RetrievalResult

    @property
    def pools(self) -> tuple[RetrievalResult, ...]:
        return self.current, self.stable, self.recovery, self.diverse

    @property
    def availability_mask(self) -> tuple[bool, bool, bool, bool]:
        return (bool(self.current.candidates), bool(self.stable.candidates),
                bool(self.recovery.candidates), bool(self.diverse.candidates))

    def pairwise_overlap(self) -> dict[tuple[str, str], int]:
        """Number of shared canonical IDs for each pair of pools."""
        ids = ({item.video_id for item in pool.candidates} for pool in self.pools)
        return {(left, right): len(left_ids & right_ids)
                for (left, left_ids), (right, right_ids) in combinations(zip(POOL_ORDER, ids), 2)}


class FourPoolRetriever:
    """Keep one reusable catalogue index and no per-user or session state."""

    def __init__(self, catalogue: Catalogue, pool_size: int = 10):
        config = RetrievalConfig(main_k=pool_size, alternative_k=pool_size,
                                 history_rule='all', outside_main_only=True)
        self._retriever = CandidateRetriever(catalogue, config)

    def initialize_state(self, categories):
        """Initialize an onboarding vector using the existing category centroids."""
        return self._retriever.initialize_state(categories)

    def retrieve_pools(self, stm_vector, ltm_vector, served_ids) -> FourPoolResult:
        history = tuple(served_ids)
        short = RetrievalState(stm_vector, history)
        long = RetrievalState(ltm_vector, history)
        return FourPoolResult(self._retriever.retrieve_relevant(short),
                              self._retriever.retrieve_relevant(long),
                              self._retriever.retrieve_recovery_alternatives(short),
                              self._retriever.retrieve_diverse_alternatives(short))
