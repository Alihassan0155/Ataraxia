"""Stage 2 local smoke check and explicit before/after state snapshots (no simulator)."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from .catalogue import EMOTIONS, DEFAULT_DATABASE, load_local_database, load_local_package
from .retrieval import CandidateRetriever, RetrievalConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--database', default=DEFAULT_DATABASE)
    source.add_argument('--package', type=Path)
    parser.add_argument('--category', action='append', help='Repeat for equal-weight selected categories')
    parser.add_argument('--updated-category', default='Nature, Animals & Conservation')
    parser.add_argument('--k', type=int, default=20)
    parser.add_argument('--alternative-k', type=int, default=20)
    parser.add_argument('--history-rule', choices=['all', 'recent', 'none'], default='all')
    parser.add_argument('--history-window', type=int, default=20)
    parser.add_argument('--min-relevance', type=float, default=.30)
    parser.add_argument('--max-relevance-drop', type=float, default=.15)
    parser.add_argument('--min-semantic-distance', type=float, default=.10)
    parser.add_argument('--min-recovery', type=float, default=.60)
    parser.add_argument('--recovery-margin', type=float, default=.05)
    parser.add_argument('--include-main', action='store_true', help='Allow alternatives inside main pool too')
    parser.add_argument('--show-candidates', action='store_true', help='Print full candidate records and eligibility')
    parser.add_argument('--report', type=Path, help='Write full results to a NEW private local file')
    args = parser.parse_args()
    config = RetrievalConfig(args.k, args.alternative_k, args.history_rule, args.history_window,
                             args.min_relevance, args.max_relevance_drop, args.min_semantic_distance,
                             args.min_recovery, args.recovery_margin, not args.include_main)
    catalogue = load_local_package(args.package) if args.package else load_local_database(args.database)
    engine = CandidateRetriever(catalogue, config)
    categories = args.category or ['Comedy', 'Music & Dance']
    state = engine.initialize_state(categories)
    searches = dict(relevant=engine.retrieve_relevant, diverse=engine.retrieve_diverse_alternatives,
                    recovery=engine.retrieve_recovery_alternatives)
    initial = {name: method(state) for name, method in searches.items()}
    # Independent full-matrix sort verifies the returned main-pool ranking.
    scores = catalogue.embeddings.astype(np.float64) @ np.array(state.interest_vector)
    expected = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), catalogue.records[i].video_id))[:args.k]
    assert [c.video_id for c in initial['relevant'].candidates] == [catalogue.records[i].video_id for i in expected]
    for name, result in initial.items():
        assert result == searches[name](state)
        assert len({c.video_id for c in result.candidates}) == len(result.candidates)
        if name != 'relevant':
            assert all(c.relevance >= result.relevance_floor for c in result.candidates)
            if config.outside_main_only:
                assert all(c.outside_main for c in result.candidates)
    # Explicit caller-supplied exposure change; no action policy, rewards or dynamics.
    watched = tuple(c.video_id for c in initial['relevant'].candidates[:3])
    exposed_state = replace(state, watched_ids=watched)
    exposed = {name: method(exposed_state) for name, method in searches.items()}
    excluded = set(watched if config.history_rule == 'all' else watched[-config.history_window:]
                   if config.history_rule == 'recent' else ())
    assert all(excluded.isdisjoint(c.video_id for c in result.candidates) for result in exposed.values())
    updated_state = engine.initialize_state([args.updated_category], watched_ids=watched)
    updated = {name: method(updated_state) for name, method in searches.items()}
    snapshots = dict(initial=initial, exposure_changed=exposed, preference_changed=updated)
    output = dict(eligible_videos=len(catalogue.records), embedding_shape=list(catalogue.embeddings.shape),
                  emotion_order=list(EMOTIONS), selected_categories=categories, updated_category=args.updated_category,
                  checks='full-matrix ranking, determinism, relevance floors, history and unique IDs passed',
                  config=asdict(config), snapshots={})
    for label, results in snapshots.items():
        output['snapshots'][label] = {
            name: dict(returned=len(result.candidates), qualifying=result.qualifying_count,
                       status=result.status, reason=result.reason, available=result.available_count,
                       excluded_history=result.excluded_history_count,
                       relevance_floor=result.relevance_floor, recovery_baseline=result.recovery_baseline,
                       outside_main=sum(c.outside_main for c in result.candidates),
                       minimum_returned_relevance=min((c.relevance for c in result.candidates), default=None))
            for name, result in results.items()}
    full = dict(summary=output, results={label: {name: asdict(result) for name, result in results.items()}
                                        for label, results in snapshots.items()})
    if args.report:
        with args.report.open('x', encoding='utf-8') as file:
            json.dump(full, file, indent=2, allow_nan=False)
            file.write('\n')
    print(json.dumps(full if args.show_candidates else output, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
