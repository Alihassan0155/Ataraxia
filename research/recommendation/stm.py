"""Training-free session preferences from public interaction feedback."""
from collections import deque
from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np

from .catalogue import Catalogue
from .retrieval import RetrievalState
from .simulator.profiles import unit


@dataclass(frozen=True)
class STMConfig:
    history_window: int = 10
    decay: float = 0.2
    beta_like: float = 0.5

    def __post_init__(self):
        if (isinstance(self.history_window, bool)
                or not isinstance(self.history_window, Integral)
                or self.history_window < 1):
            raise ValueError('history_window must be a positive integer')
        if (isinstance(self.decay, bool) or not isinstance(self.decay, Real)
                or not 0 <= self.decay <= np.finfo(np.float64).max):
            raise ValueError('decay must be finite and nonnegative')
        if (isinstance(self.beta_like, bool) or not isinstance(self.beta_like, Real)
                or not 0 <= self.beta_like <= np.finfo(np.float64).max):
            raise ValueError('beta_like must be finite and nonnegative')


class ShortTermMemory:
    """One session's public feedback and retrieval history."""

    def __init__(self, catalogue: Catalogue, onboarding_vector, config=STMConfig()):
        self._catalogue = catalogue
        self._config = config
        self._recent = deque(maxlen=config.history_window)
        self._watched_ids = []
        self.reset(onboarding_vector)

    def reset(self, onboarding_vector) -> RetrievalState:
        """Start a session using its public onboarding direction."""
        onboarding = np.asarray(onboarding_vector, dtype=np.float64)
        if onboarding.shape != (self._catalogue.embeddings.shape[1],):
            raise ValueError('onboarding_vector must match the embedding dimension')
        self._onboarding = tuple(unit(onboarding))
        self._recent.clear()
        self._watched_ids.clear()
        return self.retrieval_state()

    def update(self, video_id: str, watch_ratio: float, *, liked: bool = False) -> RetrievalState:
        """Record one interaction, including an immediate pass with ratio zero."""
        if video_id not in self._catalogue.id_to_row:
            raise ValueError(f'Unknown catalogue video ID: {video_id!r}')
        if (isinstance(watch_ratio, bool) or not isinstance(watch_ratio, Real)
                or not 0 <= watch_ratio <= 1):
            raise ValueError('watch_ratio must be finite and in [0, 1]')
        if not isinstance(liked, bool):
            raise ValueError('liked must be a boolean')
        weight = float(watch_ratio)
        if liked and self._config.beta_like:
            weight += float(self._config.beta_like)
        self._recent.append((self._catalogue.id_to_row[video_id], weight))
        self._watched_ids.append(video_id)
        return self.retrieval_state()

    def retrieval_state(self) -> RetrievalState:
        """Return a snapshot accepted by the existing candidate retriever."""
        recent = [(age, row, weight) for age, (row, weight) in
                  enumerate(reversed(self._recent)) if weight > 0]
        preference = self._onboarding
        if recent:
            # Common factors cancel under normalization. Center on the newest
            # positive event, then on the largest log weight before exponentiation.
            newest_age = recent[0][0]
            decay = float(self._config.decay)
            log_weights = [math.log(weight) - decay * (age - newest_age)
                           for age, _, weight in recent]
            peak = max(log_weights)
            total = np.zeros_like(self._onboarding, dtype=np.float64)
            for (_, row, _), log_weight in zip(recent, log_weights):
                embedding = np.asarray(self._catalogue.embeddings[row], dtype=np.float64)
                total += math.exp(log_weight - peak) * embedding
            preference = unit(total, self._onboarding)
        return RetrievalState(preference, tuple(self._watched_ids))
