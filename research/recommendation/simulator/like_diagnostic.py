"""Measure optional Like frequencies on fixed sequences from the local catalogue."""
from dataclasses import fields, replace

import numpy as np

from ..catalogue import load_local_database
from . import LikeConfig, SimulatorConfig, StepResult, SyntheticSimulator


def main():
    catalogue = load_local_database()
    config = SimulatorConfig()
    baseline = SyntheticSimulator(catalogue, config)
    enabled = SyntheticSimulator(catalogue, replace(config, like=LikeConfig()))
    profiles = range(1000, 1016)
    environments = (901, 902, 903)
    bins = ('0 (pass)', '(0, .25]', '(.25, .50]', '(.50, .75]', '(.75, 1)', '1 (complete)')
    counts = {label: [0, 0] for label in bins}
    base_fields = tuple(field.name for field in fields(StepResult))
    embeddings = catalogue.embeddings.astype(np.float64)

    for profile in profiles:
        public = baseline.reset(profile, environments[0])
        ranked = np.argsort(-(embeddings @ public.onboarding_vector), kind='stable')
        # Ten items from each of the high, middle and low onboarding-rank bands.
        middle = len(ranked) // 2
        schedule = np.concatenate((ranked[:10], ranked[middle:middle + 10], ranked[-10:]))
        for seed in environments:
            if baseline.reset(profile, seed) != enabled.reset(profile, seed):
                raise AssertionError('Onboarding differs between modes')
            for index in schedule:
                video_id = catalogue.records[index].video_id
                old, new = baseline.step(video_id), enabled.step(video_id)
                if any(getattr(old, name) != getattr(new, name) for name in base_fields):
                    raise AssertionError(f'Watch-only trajectory differs at step {old.episode_step}')
                if new.immediate_pass and new.liked:
                    raise AssertionError('Immediate passes cannot produce Likes')

                ratio = new.watch_ratio
                if ratio == 0:
                    label = bins[0]
                elif ratio == 1:
                    label = bins[-1]
                else:
                    label = bins[int(np.ceil(4 * ratio))]
                counts[label][0] += int(new.liked)
                counts[label][1] += 1

    likes = sum(pair[0] for pair in counts.values())
    impressions = sum(pair[1] for pair in counts.values())
    engaged = impressions - counts[bins[0]][1]

    def print_rate(label, numerator, denominator):
        rate = f'{numerator / denominator:.2%}' if denominator else 'n/a'
        print(f'{label}: {numerator}/{denominator} ({rate})')

    print(f'{len(catalogue.records)} videos | {len(profiles)} profiles | '
          f'{len(environments)} seeds | exact public trajectory match')
    print_rate('Per impression', likes, impressions)
    print_rate('Per engaged view', likes, engaged)
    for label, (numerator, denominator) in counts.items():
        print_rate(label, numerator, denominator)


if __name__ == '__main__':
    main()
