"""Run session STM against the local catalogue and public simulator feedback."""
import argparse
from dataclasses import replace

import numpy as np

from .catalogue import DEFAULT_DATABASE, load_local_database, load_local_package
from .retrieval import CandidateRetriever
from .simulator import LikeConfig, SimulatorConfig, SyntheticSimulator
from .stm import ShortTermMemory, STMConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--database', default=DEFAULT_DATABASE)
    source.add_argument('--package')
    parser.add_argument('--profile-seed', type=int, default=42)
    parser.add_argument('--environment-seed', type=int, default=73)
    parser.add_argument('--history-window', type=int, default=10)
    parser.add_argument('--decay', type=float, default=0.2)
    parser.add_argument('--likes', action='store_true', help='Replay public Likes alongside a beta=0 baseline')
    parser.add_argument('--beta-like', type=float, default=0.5)
    args = parser.parse_args()

    catalogue = load_local_package(args.package) if args.package else load_local_database(args.database)
    config = STMConfig(args.history_window, args.decay, args.beta_like)
    simulator = SyntheticSimulator(catalogue, SimulatorConfig(like=LikeConfig() if args.likes else None))
    observation = simulator.reset(args.profile_seed, args.environment_seed)
    baseline_config = replace(config, beta_like=0) if args.likes else config
    memory = ShortTermMemory(catalogue, observation.onboarding_vector, baseline_config)
    like_memory = ShortTermMemory(catalogue, observation.onboarding_vector, config) if args.likes else None
    retriever = CandidateRetriever(catalogue)
    pool = retriever.retrieve_relevant(memory.retrieval_state()).candidates
    print(f'{len(catalogue.records)} videos | initial pool={len(pool)}')
    differences = []
    overlaps = []
    sampled_likes = 0
    while pool:
        result = simulator.step(pool[0].video_id)
        liked = getattr(result, 'liked', False)
        state = memory.update(result.video_id, result.watch_ratio, liked=liked)
        refreshed = retriever.retrieve_relevant(state).candidates
        retained = len({item.video_id for item in pool} &
                       {item.video_id for item in refreshed})
        line = (f'{result.episode_step:02d} ratio={result.watch_ratio:.3f} '
                f'norm={np.linalg.norm(state.interest_vector):.6f} '
                f'pool={len(refreshed)} retained={retained}')
        if like_memory is not None:
            adjusted = like_memory.update(result.video_id, result.watch_ratio, liked=liked)
            adjusted_pool = retriever.retrieve_relevant(adjusted).candidates
            difference = np.linalg.norm(np.asarray(adjusted.interest_vector) - state.interest_vector)
            overlap = len({item.video_id for item in refreshed} &
                          {item.video_id for item in adjusted_pool})
            sampled_likes += int(liked)
            differences.append(difference)
            overlaps.append(overlap)
            line += f' liked={int(liked)} vector_l2={difference:.6f} top20_overlap={overlap}'
        print(line)
        if result.terminated or result.truncated:
            break
        pool = refreshed
    if differences:
        print(f'Paired beta=0 vs {config.beta_like:g} | Likes={sampled_likes}/{len(differences)} | '
              f'vector L2 mean/max/final={np.mean(differences):.6f}/{max(differences):.6f}/{differences[-1]:.6f} | '
              f'Top-20 overlap mean/min/final={np.mean(overlaps):.2f}/{min(overlaps)}/{overlaps[-1]}')


if __name__ == '__main__':
    main()
