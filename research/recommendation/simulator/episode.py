"""Own episode state and expose only completed feedback and public summaries."""
from dataclasses import dataclass
import math
from numbers import Integral
import numpy as np

from ..retrieval import CandidateRetriever
from .config import SimulatorConfig
from .profiles import generate_profile, item_qualities
from .response import start_probability, completion_probability, like_probability, watched_units
from .transition import update_interest, update_exposure


@dataclass(frozen=True)
class Observation:
    categories: tuple[str, ...]
    onboarding_vector: tuple[float, ...]
    category_exposure: tuple[tuple[str, float], ...]
    affect_exposure: tuple[float, ...]  # valence, arousal, eight emotions, recovery


@dataclass(frozen=True)
class StepResult:
    video_id: str
    watch_duration: float
    watch_ratio: float
    completed: bool
    immediate_pass: bool
    incomplete_viewing: bool
    episode_step: int
    terminated: bool
    truncated: bool
    truncation_reason: str | None
    observation: Observation


@dataclass(frozen=True)
class LikeStepResult(StepResult):
    liked: bool


class SyntheticSimulator:
    """Serve each eligible video at most once per episode, including passes."""

    def __init__(self, catalogue, config=SimulatorConfig()):
        self._retriever = CandidateRetriever(catalogue)
        self._config = config
        self._catalogue = catalogue
        self._categories = sorted({record.category for record in catalogue.records})
        if len(self._categories) < config.category_count:
            raise ValueError('Catalogue has fewer categories than requested')
        self._category_vectors = dict(zip(self._categories, np.eye(len(self._categories))))
        self._features = {}
        for record in catalogue.records:
            duration = record.duration_seconds
            affect = np.array([record.valence, record.arousal, *record.emotions, record.recovery_suitability])
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ValueError(f'Invalid duration for {record.video_id}')
            if (affect.shape != (11,) or not np.isfinite(affect).all()
                    or not -1 <= affect[0] <= 1 or np.any(affect[1:] < 0)
                    or np.any(affect[1:] > 1) or not .99 - 1e-12 <= math.fsum(affect[2:10]) <= 1.01 + 1e-12):
                raise ValueError(f'Invalid affect for {record.video_id}')
            self._features[record.video_id] = affect
        self._profile = None

    def reset(self, profile_seed, environment_seed, *, quality_seed=None):
        if quality_seed is None:
            quality_seed = environment_seed
        for seed in (profile_seed, environment_seed, quality_seed):
            if isinstance(seed, bool) or not isinstance(seed, Integral) or seed < 0:
                raise ValueError('Seeds must be nonnegative integers')
        self._profile = generate_profile(self._retriever, self._categories, self._config, profile_seed)
        self._quality = item_qualities(self._features, quality_seed, self._config.quality_constant)
        self._seed = environment_seed
        self._profile_key = tuple(map(int, np.random.SeedSequence(profile_seed).generate_state(4)))
        self._like_propensity = 0.0
        if self._config.like is not None and self._config.like.propensity_scale:
            rng = np.random.default_rng(np.random.SeedSequence(profile_seed, spawn_key=(5,)))
            self._like_propensity = float(self._config.like.propensity_scale) * rng.standard_normal()
        self._interest = self._profile.interest.copy()
        self._category_exposure = np.zeros(len(self._categories))
        self._affect_exposure = np.zeros(11)
        self._served = set()
        self._done = False
        return self._observe()

    def _observe(self):
        return Observation(self._profile.categories, self._profile.onboarding,
                           tuple(zip(self._categories, map(float, self._category_exposure))),
                           tuple(map(float, self._affect_exposure)))

    def _channel(self, number, step):
        key = (number, step, *self._profile_key)
        return np.random.default_rng(np.random.SeedSequence(self._seed, spawn_key=key))

    def step(self, video_id):
        if self._profile is None or self._done:
            raise RuntimeError('Reset before stepping a new episode')
        if video_id not in self._features or video_id in self._served:
            raise ValueError('Expected an eligible video ID not yet served in this episode')
        row = self._catalogue.id_to_row[video_id]
        record = self._catalogue.records[row]
        embedding = self._catalogue.embeddings[row]
        category = self._category_vectors[record.category]
        exposure = float(category @ self._category_exposure)
        step = len(self._served) + 1
        config = self._profile.config

        start = start_probability(float(np.linalg.norm(embedding - self._interest)), exposure, config)
        engaged = bool(self._channel(1, step).random() < start)
        units = 0
        if engaged:
            affinity = float(self._interest @ embedding)
            completion = completion_probability(affinity,
                                                self._quality[video_id], exposure, config)
            units = watched_units(completion, config.progress_units, self._channel(2, step).random())
        ratio = units / config.progress_units
        liked = False
        if config.like is not None and engaged:
            chance = like_probability(affinity, ratio, self._like_propensity, config.like)
            liked = bool(self._channel(4, step).random() < chance)
        self._interest = update_interest(self._interest, embedding, self._quality[video_id],
                                         engaged, config, self._channel(3, step))
        self._category_exposure = update_exposure(self._category_exposure, category, ratio,
                                                  config.repetition_retention)
        self._affect_exposure = update_exposure(self._affect_exposure, self._features[video_id],
                                               ratio, config.exposure_retention)
        self._served.add(video_id)
        reason = None
        if step == config.horizon:
            reason = 'horizon'
        elif step == len(self._features):
            reason = 'catalogue_exhausted'
        self._done = reason is not None
        completed = units == config.progress_units
        result = (video_id, record.duration_seconds * ratio, ratio, completed,
                  not engaged, not completed, step, False, self._done, reason, self._observe())
        if config.like is not None:
            return LikeStepResult(*result, liked=liked)
        return StepResult(*result)
