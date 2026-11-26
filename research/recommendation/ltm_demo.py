"""Replay public feedback into separate session and long-term memories."""
import argparse

import numpy as np

from .catalogue import load_local_database
from .ltm import LongTermMemory
from .retrieval import CandidateRetriever
from .simulator import LikeConfig, SimulatorConfig, SyntheticSimulator
from .stm import ShortTermMemory


def distance(left, right):
    return np.linalg.norm(np.asarray(left) - right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-seed', type=int, default=42)
    parser.add_argument('--environment-seeds', type=int, nargs='+', default=[901, 902, 903])
    parser.add_argument('--quality-seed', type=int, default=901)
    args = parser.parse_args()
    catalogue = load_local_database()
    simulator = SyntheticSimulator(catalogue, SimulatorConfig(like=LikeConfig()))
    retriever = CandidateRetriever(catalogue)
    onboarding = simulator.reset(args.profile_seed, args.environment_seeds[0],
                                 quality_seed=args.quality_seed).onboarding_vector
    stm = ShortTermMemory(catalogue, onboarding)
    ltm = LongTermMemory(catalogue, onboarding)
    origin = ltm.retrieval_state().interest_vector
    previous_end = origin
    print(f'{len(catalogue.records)} videos | profile={args.profile_seed} | quality seed={args.quality_seed}')
    for seed in args.environment_seeds:
        public = simulator.reset(args.profile_seed, seed, quality_seed=args.quality_seed)
        short = stm.reset(public.onboarding_vector)
        long = ltm.retrieval_state(short.watched_ids)
        start_short, start_long = short.interest_vector, long.interest_vector
        assert start_long == previous_end
        assert start_short == origin and not short.watched_ids
        likes = updates = steps = 0
        overlaps = []
        pool = retriever.retrieve_relevant(short).candidates
        while True:
            result = simulator.step(pool[0].video_id)
            short = stm.update(result.video_id, result.watch_ratio, liked=result.liked)
            weight = ltm.update(result.video_id, result.watch_ratio, liked=result.liked,
                                immediate_pass=result.immediate_pass)
            long = ltm.retrieval_state(short.watched_ids)
            pool = retriever.retrieve_relevant(short).candidates
            short_ids = {item.video_id for item in pool}
            long_ids = {item.video_id for item in retriever.retrieve_relevant(long).candidates}
            overlaps.append(len(short_ids & long_ids))
            steps += 1
            likes += int(result.liked)
            updates += int(weight > 0)
            if result.terminated or result.truncated:
                break
        previous_end = long.interest_vector
        print(f'seed={seed} | steps={steps} Likes={likes} eligible={updates} | '
              f'STM session L2={distance(short.interest_vector, start_short):.6f} | '
              f'LTM session L2={distance(previous_end, start_long):.6f} '
              f'cumulative L2={distance(previous_end, origin):.6f} | '
              f'Top-20 overlap mean/min/final={np.mean(overlaps):.2f}/{min(overlaps)}/{overlaps[-1]}')


if __name__ == '__main__':
    main()
