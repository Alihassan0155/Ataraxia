"""Provisional v0.2 parameters for one synthetic population."""
from dataclasses import dataclass, fields
from numbers import Real
import sys
import math


@dataclass(frozen=True)
class LikeConfig:
    """Provisional coefficients for the optional explicit feedback model."""

    intercept: float = -4.0
    affinity_coefficient: float = 1.0
    watch_ratio_coefficient: float = 1.0
    propensity_scale: float = 0.0

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not -sys.float_info.max / 64 <= value <= sys.float_info.max / 64):
                raise ValueError(f'{field.name} must be a finite real in the safe Like range')
            if field.name != 'intercept' and value < 0:
                raise ValueError(f'{field.name} must be nonnegative')


@dataclass(frozen=True)
class SimulatorConfig:
    horizon: int = 30
    category_count: int = 2
    concentration: float = 1.0
    initial_noise: float = 0.10
    quality_constant: float | None = None
    start_intercept: float = 2.0
    affinity_weight: float = 2.0
    quality_weight: float = 0.25
    watch_intercept: float = 0.0
    watch_weight: float = 1.0
    progress_units: int = 20
    interest_rate: float = 0.02
    transition_noise: float = 0.005
    repetition_retention: float = 0.8
    repetition_weight: float = 1.0
    exposure_retention: float = 0.8
    lapse: float = 0.0
    like: LikeConfig | None = None

    def __post_init__(self):
        if self.like is not None and not isinstance(self.like, LikeConfig):
            raise ValueError('like must be a LikeConfig or None')
        for name, minimum in [('horizon', 1), ('category_count', 1), ('progress_units', 2)]:
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                raise ValueError(f'{name} must be an integer >= {minimum}')
        for field in fields(self):
            if field.name == 'like':
                continue
            value = getattr(self, field.name)
            if field.name == 'quality_constant' and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Real) or abs(value) > sys.float_info.max or not math.isfinite(value):
                raise ValueError(f'{field.name} must be a finite real number')
        # Allow headroom for the sum of terms in either response logit.
        for name in ('start_intercept', 'watch_intercept', 'affinity_weight', 'watch_weight', 'repetition_weight'):
            if abs(getattr(self, name)) > sys.float_info.max / 8:
                raise ValueError(f'{name} exceeds the safe logit range')
        for name in ('start_intercept', 'watch_intercept', 'initial_noise', 'affinity_weight',
                     'watch_weight', 'transition_noise', 'repetition_weight', 'concentration'):
            value = getattr(self, name)
            if not name.endswith('intercept') and value < 0:
                raise ValueError(f'Invalid {name}')
        if not sys.float_info.min <= self.concentration <= sys.float_info.max / self.category_count / 8:
            raise ValueError('concentration is outside the safe Dirichlet range')
        for name in ('quality_weight', 'interest_rate', 'lapse'):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f'{name} must be in [0, 1]')
        for name in ('repetition_retention', 'exposure_retention'):
            if not 0 <= getattr(self, name) < 1:
                raise ValueError(f'{name} must be in [0, 1)')
        if self.quality_constant is not None and not -1 <= self.quality_constant <= 1:
            raise ValueError('quality_constant must be in [-1, 1]')
