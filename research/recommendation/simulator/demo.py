"""Run paired stationary-onboarding baselines on the local catalogue."""
import argparse
from dataclasses import replace

from ..catalogue import load_local_database
from ..retrieval import CandidateRetriever, RetrievalState
from . import SimulatorConfig, SyntheticSimulator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-seed', type=int, default=42)
    parser.add_argument('--environment-seed', type=int, default=73)
    args = parser.parse_args()
    catalogue = load_local_database()
    retriever = CandidateRetriever(catalogue)
    for weight in (0.0, 0.25, 2.0):
        simulator = SyntheticSimulator(catalogue, replace(SimulatorConfig(), repetition_weight=weight))
        observation = simulator.reset(args.profile_seed, args.environment_seed)
        print(f'\nRepetition weight {weight:g} | {", ".join(observation.categories)} | {len(catalogue.records)} videos')
        history = []
        results = []
        while True:
            state = RetrievalState(observation.onboarding_vector, tuple(history))
            candidate = retriever.retrieve_relevant(state).candidates[0]
            result = simulator.step(candidate.video_id)
            history.append(result.video_id)
            results.append(result)
            observation = result.observation
            record = catalogue.records[catalogue.id_to_row[result.video_id]]
            exposure = dict(observation.category_exposure)[record.category]
            print(f'{result.episode_step:02d} {result.video_id} | {record.category} | '
                  f'{result.watch_duration:.2f}/{record.duration_seconds:.2f}s '
                  f'ratio={result.watch_ratio:.2f} complete={int(result.completed)} '
                  f'pass={int(result.immediate_pass)} category_exposure={exposure:.3f}')
            if result.truncated:
                break
        print(f'{len(results)} steps | {result.truncation_reason} | '
              f'passes={sum(r.immediate_pass for r in results)} '
              f'completions={sum(r.completed for r in results)} '
              f'watch_seconds={sum(r.watch_duration for r in results):.2f} '
              f'mean_ratio={sum(r.watch_ratio for r in results)/len(results):.3f}')


if __name__ == '__main__':
    main()
