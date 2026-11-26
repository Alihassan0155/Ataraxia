"""Single-video outside-option choice and censored geometric watching."""
import math


def probability(logit, lapse):
    # Stable binary softmax with outside-option logit zero.
    exponential = math.exp(-abs(logit))
    sigmoid = 1 / (1 + exponential) if logit >= 0 else exponential / (1 + exponential)
    return (1 - lapse) * sigmoid + lapse / 2


def start_probability(distance, exposure, config):
    return probability(config.start_intercept - config.affinity_weight * distance
                       - config.repetition_weight * exposure, config.lapse)


def completion_probability(affinity, quality, exposure, config):
    utility = (1 - config.quality_weight) * affinity + config.quality_weight * quality
    return probability(config.watch_intercept + config.watch_weight * utility
                       - config.repetition_weight * exposure, config.lapse)


def like_probability(affinity, watch_ratio, propensity, config):
    affinity = max(-1.0, min(1.0, affinity))
    logit = (float(config.intercept) + float(config.affinity_coefficient) * affinity
             + float(config.watch_ratio_coefficient) * watch_ratio + propensity)
    return probability(logit, lapse=0.0)


def watched_units(completion, units, draw):
    """Inverse survival sampling of 1 + min(Geom_0(p), units - 1)."""
    if completion == 1 or draw < completion:
        return units
    if completion == 0:
        return 1
    log_continue = math.log(completion) / (units - 1)
    return 1 + min(units - 2, int(math.log(draw) / log_continue))
