"""Private preference update and consumption-weighted exposure."""
from .profiles import noisy_direction


def update_interest(interest, embedding, quality, engaged, config, rng):
    if not engaged or (config.interest_rate == 0 and config.transition_noise == 0):
        return interest
    center = interest + config.interest_rate * quality * (embedding - interest)
    return noisy_direction(center, config.transition_noise, rng, interest)


def update_exposure(previous, features, ratio, retention):
    return retention * previous + (1 - retention) * ratio * features
