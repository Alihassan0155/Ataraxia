"""Independent seeded profile and item-quality generation."""
from dataclasses import dataclass
import numpy as np

from .config import SimulatorConfig


@dataclass(frozen=True)
class _Profile:
    categories: tuple[str, ...]
    onboarding: tuple[float, ...]
    interest: np.ndarray
    config: SimulatorConfig


def unit(vector, fallback=None, *, minimum_norm=1e-12):
    vector = np.asarray(vector, dtype=np.float64)
    if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError('Expected a finite, nonempty interest vector')
    scale = np.max(np.abs(vector))
    if scale:
        scaled = vector / scale
        norm = np.linalg.norm(scaled)
        if scale >= minimum_norm / norm:
            return scaled / norm
    if fallback is None:
        raise ValueError('Undefined interest direction')
    if np.shape(fallback) != vector.shape:
        raise ValueError('Fallback must match the interest vector shape')
    return unit(fallback)


def noisy_direction(center, noise, rng, fallback):
    """Normalize the Gaussian proposal without ever forming an oversized vector."""
    std = noise / np.sqrt(center.size)
    scale = max(1.0, std)
    proposal = center / scale + (std / scale) * rng.normal(size=center.size)
    return unit(proposal, fallback, minimum_norm=1e-12 / scale)


def generate_profile(retriever, categories, config, seed):
    rng = np.random.default_rng(seed)
    selected = tuple(sorted(rng.choice(categories, config.category_count, replace=False).tolist()))
    onboarding = retriever.initialize_state(selected).interest_vector
    weights = rng.dirichlet(np.full(len(selected), config.concentration))
    centroids = np.array([retriever.initialize_state([name]).interest_vector for name in selected])
    latent = noisy_direction(weights @ centroids, config.initial_noise, rng, onboarding)
    return _Profile(selected, onboarding, latent, config)


def item_qualities(ids, seed, constant):
    rng = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(0,)))
    return {video_id: float(rng.uniform(-1, 1)) if constant is None else float(constant)
            for video_id in sorted(ids)}
