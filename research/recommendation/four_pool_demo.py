"""Measure four-pool retrieval on reproducible local feedback snapshots."""
from time import perf_counter

import numpy as np

from .catalogue import load_local_database
from .four_pools import FourPoolRetriever, POOL_ORDER
from .ltm import LongTermMemory
from .simulator import LikeConfig, SimulatorConfig, SyntheticSimulator
from .stm import ShortTermMemory


def main():
    catalogue = load_local_database()
    retriever = FourPoolRetriever(catalogue)
    simulator = SyntheticSimulator(catalogue, SimulatorConfig(like=LikeConfig()))
    observation = simulator.reset(42, 901)
    stm = ShortTermMemory(catalogue, observation.onboarding_vector)
    ltm = LongTermMemory(catalogue, observation.onboarding_vector)
    print(f'{len(catalogue.records)} videos | profile=42 | environment=901 | K=10')
    print('Pool order:', ', '.join(POOL_ORDER))
    durations = []

    for step in range(31):
        short = stm.retrieval_state()
        long = ltm.retrieval_state()
        started = perf_counter()
        result = retriever.retrieve_pools(short.interest_vector, long.interest_vector,
                                         short.watched_ids)
        durations.append((perf_counter() - started) * 1000)
        sizes = tuple(len(pool.candidates) for pool in result.pools)
        overlaps = ' '.join(f'{a}/{b}={n}' for (a, b), n in result.pairwise_overlap().items())
        print(f'{step:02d} | mask={result.availability_mask} | sizes={sizes} | {overlaps}')
        if step == 30:
            break
        feedback = simulator.step(result.current.candidates[0].video_id)
        stm.update(feedback.video_id, feedback.watch_ratio, liked=feedback.liked)
        ltm.update(feedback.video_id, feedback.watch_ratio, liked=feedback.liked,
                   immediate_pass=feedback.immediate_pass)

    print(f'Bundle latency ms | median={np.median(durations):.2f} '
          f'p95={np.percentile(durations, 95):.2f} max={max(durations):.2f}')


if __name__ == '__main__':
    main()
