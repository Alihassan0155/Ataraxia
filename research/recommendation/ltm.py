"""User-scoped, training-free long-term preference memory."""
from dataclasses import dataclass
from numbers import Real

import numpy as np

from .catalogue import Catalogue
from .retrieval import RetrievalState
from .simulator.profiles import unit


@dataclass(frozen=True)
class LTMConfig:
    alpha_l: float = 0.02
    threshold: float = 0.8
    beta_l: float = 0.5

    def __post_init__(self):
        for name in ('alpha_l', 'threshold', 'beta_l'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not 0 <= value <= 1:
                raise ValueError(f'{name} must be finite and in [0, 1]')


class LongTermMemory:
    """Keep one user's preference in memory across session boundaries."""

    def __init__(self, catalogue: Catalogue, onboarding_vector, config=LTMConfig()):
        self._catalogue = catalogue
        self._config = config
        self.reset_for_user(onboarding_vector)

    def reset_for_user(self, onboarding_vector) -> None:
        """Replace the previous user's direction with the new onboarding centroid."""
        onboarding = np.asarray(onboarding_vector, dtype=np.float64)
        if onboarding.shape != (self._catalogue.embeddings.shape[1],):
            raise ValueError('onboarding_vector must match the embedding dimension')
        self._interest = tuple(unit(onboarding))

    def update(self, video_id: str, watch_ratio: float, *,
               liked: bool = False, immediate_pass: bool = False) -> float:
        """Apply one public interaction and return its feedback weight q."""
        if video_id not in self._catalogue.id_to_row:
            raise ValueError(f'Unknown catalogue video ID: {video_id!r}')
        if (isinstance(watch_ratio, bool) or not isinstance(watch_ratio, Real)
                or not 0 <= watch_ratio <= 1):
            raise ValueError('watch_ratio must be finite and in [0, 1]')
        if not isinstance(liked, bool) or not isinstance(immediate_pass, bool):
            raise ValueError('liked and immediate_pass must be booleans')

        ratio = float(watch_ratio)
        if immediate_pass or ratio == 0:
            return 0.0
        if liked:
            weight = 1.0
        elif ratio >= self._config.threshold:
            weight = float(self._config.beta_l) * ratio
        else:
            return 0.0

        rate = float(self._config.alpha_l) * weight
        if rate > 0:
            previous = np.asarray(self._interest, dtype=np.float64)
            embedding = np.asarray(self._catalogue.embeddings[self._catalogue.id_to_row[video_id]],
                                   dtype=np.float64)
            proposal = (1 - rate) * previous + rate * embedding
            self._interest = tuple(unit(proposal, previous))
        return weight

    def retrieval_state(self, watched_ids=()) -> RetrievalState:
        """Use the caller's current session history for retrieval exclusions."""
        return RetrievalState(self._interest, watched_ids)
