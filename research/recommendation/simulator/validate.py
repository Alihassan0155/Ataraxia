"""Stage 3B crossed, paired experiments on the retained local catalogue."""
import argparse
from dataclasses import replace
import json

import numpy as np

from ..catalogue import load_local_database
from . import SimulatorConfig, SyntheticSimulator
from .response import start_probability, completion_probability

PROFILES = tuple(range(1000, 1128))
ENVIRONMENTS = (901, 902, 903, 904, 905, 906)
DEFAULT = SimulatorConfig()
STATIONARY = replace(DEFAULT, interest_rate=0, transition_noise=0)
CONDITIONS = {
    'default': DEFAULT,
    'stationary': STATIONARY,
    'repeat_zero': replace(STATIONARY, repetition_weight=0),
    'repeat_low': replace(STATIONARY, repetition_weight=.25),
    'repeat_high': replace(STATIONARY, repetition_weight=2),
    'quality_negative': replace(STATIONARY, repetition_weight=0, quality_constant=-1),
    'quality_positive': replace(STATIONARY, repetition_weight=0, quality_constant=1),
    'lapse_half': replace(DEFAULT, lapse=.5),
    'lapse_full': replace(DEFAULT, lapse=1),
}
METRICS = ('engage', 'complete', 'ratio', 'seconds', 'p_start', 'p_complete',
           'exposure', 'cosine', 'drift', 'saturated_start', 'saturated_complete')


def interval(values, weights_profile, weights_seed):
    estimates = np.einsum('bi,ij,bj->b', weights_profile, values, weights_seed)
    return dict(mean=float(values.mean()), profile_sd=float(values.mean(axis=1).std(ddof=1)),
                seed_means=values.mean(axis=0).tolist(),
                ci95=np.quantile(estimates, [.025, .975]).tolist())


def run(catalogue):
    rng = np.random.default_rng(303)
    profile_weights = rng.multinomial(len(PROFILES), np.ones(len(PROFILES))/len(PROFILES), 2000)/len(PROFILES)
    seed_weights = rng.multinomial(len(ENVIRONMENTS), np.ones(len(ENVIRONMENTS))/len(ENVIRONMENTS), 2000)/len(ENVIRONMENTS)

    def summary(values):
        return interval(values, profile_weights, seed_weights)

    # Fixed schedule per profile from public onboarding only. Ten primary
    # category items, ten from the other category, then ten primary items.
    # Rank using all eligible vectors before filtering by category.
    games = {name: SyntheticSimulator(catalogue, cfg) for name, cfg in CONDITIONS.items()}
    near_far = {name: SyntheticSimulator(catalogue, replace(STATIONARY, lapse=lapse))
                for name, lapse in [('semantic', 0), ('semantic_lapse', 1)]}
    grid = (len(PROFILES), len(ENVIRONMENTS))
    results = {name: np.empty((*grid, 30, len(METRICS))) for name in games}
    probes = {name: np.empty((*grid, 2, 3)) for name in near_far}
    categories = np.array([r.category for r in catalogue.records])
    ids = catalogue.video_ids
    presented = set()
    counts = {category: int(np.sum(categories == category)) for category in set(categories)}
    fallback_profiles = 0
    max_norm_error = 0.
    for u, profile in enumerate(PROFILES):
        public = games['default'].reset(profile, ENVIRONMENTS[0])
        ordered = np.argsort(-(catalogue.embeddings @ public.onboarding_vector), kind='stable')
        first, second = public.categories
        if counts[first] < 20 or counts[second] < 10:
            # Keep small-category users. Choose viable blocks by public rank.
            first = next(categories[i] for i in ordered if counts[categories[i]] >= 20)
            second = next(categories[i] for i in ordered
                          if categories[i] != first and counts[categories[i]] >= 10)
            fallback_profiles += 1
        primary, other = [ordered[categories[ordered] == category] for category in (first, second)]
        schedule = np.concatenate((primary[:10], other[:10], primary[10:20]))
        assert len(schedule) == len(set(schedule)) == 30
        presented.update(ids[schedule].tolist())
        for j, seed in enumerate(ENVIRONMENTS):
            for name, game in games.items():
                cfg = CONDITIONS[name]
                observation = game.reset(profile, seed)
                initial = game._interest.copy()
                for t, index in enumerate(schedule):
                    record = catalogue.records[index]
                    e = catalogue.embeddings[index]
                    before = game._interest.copy()
                    cosine = float(before @ e)
                    exposure = dict(observation.category_exposure)[record.category]
                    start = start_probability(float(np.linalg.norm(e-before)), exposure, cfg)
                    finish = completion_probability(cosine, game._quality[record.video_id], exposure, cfg)
                    step = game.step(record.video_id)
                    observation = step.observation
                    max_norm_error = max(max_norm_error, abs(float(np.linalg.norm(game._interest))-1))
                    assert step.completed == (step.watch_ratio == 1)
                    assert 0 <= step.watch_duration <= record.duration_seconds
                    assert step.immediate_pass == (step.watch_ratio == 0)
                    assert not step.terminated and step.truncated == (t == 29)
                    assert step.truncation_reason == ('horizon' if t == 29 else None)
                    if step.immediate_pass or cfg.interest_rate == cfg.transition_noise == 0:
                        np.testing.assert_array_equal(game._interest, before)
                    results[name][u,j,t] = (
                        not step.immediate_pass, step.completed, step.watch_ratio,
                        step.watch_duration, start, finish,
                        dict(observation.category_exposure)[first], cosine,
                        np.linalg.norm(game._interest-initial),
                        start < .01 or start > .99, finish < .01 or finish > .99,
                    )
            # Both first-step interventions reuse exactly the same RNG draws.
            for name, game in near_far.items():
                for k, index in enumerate((ordered[0], ordered[-1])):
                    game.reset(profile, seed)
                    cosine = game._interest @ catalogue.embeddings[index]
                    step = game.step(str(ids[index]))
                    probes[name][u,j,k] = cosine, not step.immediate_pass, step.watch_ratio

    index = {label: i for i, label in enumerate(METRICS)}
    sessions = {name: x.mean(axis=2) for name, x in results.items()}
    paired = {}
    for left, right in [('repeat_high','repeat_low'), ('repeat_low','repeat_zero'),
                        ('quality_positive','quality_negative'), ('default','stationary'),
                        ('lapse_half','default'), ('lapse_full','default')]:
        paired[f'{left} minus {right}'] = {
            m: summary((sessions[left]-sessions[right])[..., index[m]])
            for m in METRICS[:4]
        }
    np.testing.assert_array_equal(results['quality_negative'][..., 0], results['quality_positive'][..., 0])
    np.testing.assert_array_equal(probes['semantic_lapse'][:,:,0,1:], probes['semantic_lapse'][:,:,1,1:])
    for x in results.values():
        np.testing.assert_allclose(x[:,:,19,index['exposure']], x[:,:,9,index['exposure']] * .8**10)
    # Audit finite-sample association across the entire catalogue, not served items.
    quality_game = games['default']
    quality_features = np.array([[r.duration_seconds, r.valence, r.arousal, r.recovery_suitability, r.confidence,
                                  *r.emotions] for r in catalogue.records])
    correlations = []
    for seed in ENVIRONMENTS:
        quality_game.reset(PROFILES[0], seed)
        q = np.array([quality_game._quality[str(i)] for i in ids])
        correlations.append(np.corrcoef(q, quality_features.T)[0,1:].tolist())
    baseline = results['default']
    engaged = baseline[...,0].astype(bool)
    return {
        'catalogue_size': len(ids), 'distinct_videos_served': len(presented),
        'fallback_profiles': fallback_profiles, 'profiles': PROFILES, 'environment_seeds': ENVIRONMENTS,
        'conditions': {name: {m: summary(v[..., index[m]]) for m in METRICS} for name,v in sessions.items()},
        'paired': paired,
        'semantic_probes': {name: {m: summary((x[:,:,0]-x[:,:,1])[...,i])
                                   for i,m in enumerate(('cosine','engage','ratio'))} for name,x in probes.items()},
        'exposure_after_steps_10_20_30': {name: [summary(x[:,:,t,index['exposure']]) for t in (9,19,29)]
                                          for name,x in results.items()},
        'final_drift': {name: summary(x[:,:,29,index['drift']]) for name,x in results.items()},
        'default_distribution': {
            'quantiles': [0,.1,.25,.5,.75,.9,1],
            'seconds': np.quantile(baseline[...,3], [0,.1,.25,.5,.75,.9,1]).tolist(),
            'ratio': np.quantile(baseline[...,2], [0,.1,.25,.5,.75,.9,1]).tolist(),
            'engaged_incomplete_ratio': np.quantile(baseline[...,2][engaged & ~baseline[...,1].astype(bool)], [0,.1,.25,.5,.75,.9,1]).tolist(),
            'start_probability_range': [float(baseline[...,4].min()),float(baseline[...,4].max())],
            'conditional_completion_range': [float(baseline[...,5].min()),float(baseline[...,5].max())],
            'conditional_completion': float(baseline[...,1].sum()/engaged.sum()),
        },
        'max_unit_norm_error': max_norm_error,
        'quality_correlation_columns': ['duration','valence','arousal','recovery','confidence',
                                        'joy','sadness','anger','fear_anxiety','surprise','disgust','calm_contentment','neutral'],
        'quality_correlations_by_seed': correlations,
    }


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run(load_local_database()), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
