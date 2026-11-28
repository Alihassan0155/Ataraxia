"""Local Streamlit playground for the completed research components."""
from collections import Counter
from pathlib import Path
from uuid import uuid4

import numpy as np
from psycopg import Error as DatabaseError
import streamlit as st

from research.recommendation.catalogue import EMOTIONS, load_local_database
from research.recommendation.ltm import LongTermMemory
from research.recommendation.four_pools import FourPoolRetriever, POOL_ORDER
from research.recommendation.simulator import LikeConfig, SimulatorConfig, SyntheticSimulator
from research.recommendation.stm import ShortTermMemory

ROOT = Path(__file__).resolve().parents[3]
MEDIA_SUFFIXES = {'.mp4', '.webm', '.mov'}


@st.cache_resource
def catalogue_resources():
    catalogue = load_local_database()
    return catalogue, FourPoolRetriever(catalogue)


@st.cache_data
def local_previews(video_ids):
    """Index unambiguous local files named by their exact canonical video ID."""
    wanted = set(video_ids)
    matches = {}
    for path in (ROOT / 'data').rglob('*'):
        if path.stem in wanted and path.suffix.lower() in MEDIA_SUFFIXES and path.is_file():
            resolved = path.resolve()
            if resolved.is_relative_to(ROOT):
                matches.setdefault(path.stem, set()).add(resolved)
    return {video_id: str(next(iter(paths))) for video_id, paths in matches.items()
            if len(paths) == 1}


class Playground:
    """Own one browser user's memories and one session's public state."""

    def __init__(self, catalogue, retriever, categories, mode, profile_seed, environment_seed):
        self.catalogue = catalogue
        self.retriever = retriever
        self.categories = tuple(categories)
        self.onboarding = retriever.initialize_state(categories).interest_vector
        self.stm = ShortTermMemory(catalogue, self.onboarding)
        self.ltm = LongTermMemory(catalogue, self.onboarding)
        self.new_session(mode, profile_seed, environment_seed)

    def new_session(self, mode, profile_seed, environment_seed):
        simulator = None
        public = None
        if mode == 'Simulator':
            simulator = SyntheticSimulator(self.catalogue, SimulatorConfig(like=LikeConfig()))
            public = simulator.reset(profile_seed, environment_seed)
        self.session_id = uuid4().hex
        self.mode = mode
        self.simulator = simulator
        self.simulator_categories = public.categories if public else ()
        self.done = False
        self.feedback = []
        self.stm.reset(self.onboarding)
        self.session_vectors = self.vectors()
        self.previous = None
        self.current = self.retrieve()

    def vectors(self):
        return (self.stm.retrieval_state().interest_vector,
                self.ltm.retrieval_state().interest_vector)

    def retrieve(self):
        short = self.stm.retrieval_state()
        long = self.ltm.retrieval_state()
        return self.retriever.retrieve_pools(short.interest_vector, long.interest_vector, short.watched_ids)

    @property
    def revision(self):
        return f'{self.session_id}-{len(self.feedback)}'

    def submit(self, revision, video_id, ratio, liked, immediate_pass):
        if revision != self.revision or self.done:
            return
        if video_id not in self.catalogue.id_to_row or video_id in self.stm.retrieval_state().watched_ids:
            raise ValueError('Choose an eligible video that has not been served this session.')
        if self.simulator is not None:
            result = self.simulator.step(video_id)
            ratio, liked, immediate_pass = result.watch_ratio, result.liked, result.immediate_pass
            self.done = result.terminated or result.truncated
        elif immediate_pass or ratio == 0:
            ratio, liked, immediate_pass = 0.0, False, True

        self.stm.update(video_id, ratio, liked=liked)
        weight = self.ltm.update(video_id, ratio, liked=liked, immediate_pass=immediate_pass)
        short, long = self.vectors()
        short_start, long_start = self.session_vectors
        record = self.catalogue.records[self.catalogue.id_to_row[video_id]]
        self.feedback.append({
            'Interaction': len(self.feedback) + 1, 'Video ID': video_id,
            'Category': record.category, 'Watch ratio': ratio, 'Like': liked,
            'Immediate pass': immediate_pass, 'LTM weight': weight,
            'STM drift': float(np.linalg.norm(np.asarray(short) - short_start)),
            'LTM drift': float(np.linalg.norm(np.asarray(long) - long_start)),
        })
        self.previous, self.current = self.current, self.retrieve()


def pool_rows(catalogue, result):
    return [
        {'Rank': rank, 'Video ID': item.video_id,
         'Title': catalogue.records[catalogue.id_to_row[item.video_id]].title,
         'Category': item.category, 'Similarity': round(item.relevance, 4),
         'Dominant emotion': item.affect.dominant_emotion,
         'Valence': item.affect.valence, 'Arousal': item.affect.arousal,
         'Recovery suitability': item.affect.recovery_suitability,
         'Confidence': item.affect.confidence}
        for rank, item in enumerate(result.candidates, 1)
    ]


def show_pools(playground):
    bundle = playground.current
    st.caption(' · '.join(f'{name} {len(pool.candidates)}/{pool.requested_k} '
                          f'({"available" if available else "unavailable"})'
                          for name, pool, available in
                          zip(POOL_ORDER, bundle.pools, bundle.availability_mask)))
    for name, result, tab in zip(POOL_ORDER, bundle.pools, st.tabs(POOL_ORDER)):
        with tab:
            if name in ('Diverse', 'Recovery'):
                st.caption('Uses STM relevance and the Current pool as its reference.')
            if result.reason:
                st.info(result.reason.replace('_', ' ').capitalize())
            if result.candidates:
                st.dataframe(pool_rows(playground.catalogue, result), hide_index=True)


def show_video_and_feedback(playground, previews):
    ids = list(dict.fromkeys(item.video_id for result in playground.current.pools
                            for item in result.candidates))
    if not ids:
        st.info('No candidates remain. Start a new session to clear served-video exclusions.')
        return
    catalogue = playground.catalogue

    def label(video_id):
        title = catalogue.records[catalogue.id_to_row[video_id]].title
        return f'{title} · {video_id}' if title else video_id

    video_id = st.selectbox('Inspect a candidate', ids, format_func=label)
    record = catalogue.records[catalogue.id_to_row[video_id]]
    detail, feedback = st.columns((3, 2))
    with detail:
        membership = [name for name, pool in zip(POOL_ORDER, playground.current.pools)
                      if any(item.video_id == video_id for item in pool.candidates)]
        st.caption(f'{record.category} · {", ".join(membership)}')
        if video_id in previews:
            st.video(previews[video_id])
        else:
            st.caption('Local video preview unavailable.')
        with st.expander('Gemini affect annotation'):
            st.json({
                'Dominant emotion': record.dominant_emotion, 'Valence': record.valence,
                'Arousal': record.arousal, 'Recovery suitability': record.recovery_suitability,
                'Confidence': record.confidence, 'Emotions': dict(zip(EMOTIONS, record.emotions)),
            })
    with feedback:
        if playground.done:
            st.info('The simulator episode ended. Start a new session to continue.')
            return
        revision = playground.revision
        with st.form(f'feedback-{revision}-{video_id}'):
            if playground.mode == 'Manual':
                ratio = st.slider('Watch ratio', 0.0, 1.0, 0.5, 0.05)
                liked = st.checkbox('Like')
                immediate_pass = st.checkbox('Immediate pass')
                st.caption('A pass or zero watch ratio overrides Like.')
            else:
                ratio, liked, immediate_pass = 0.0, False, False
                st.caption('The seeded simulator supplies watch ratio, Like and pass feedback.')
            submitted = st.form_submit_button('Submit feedback' if playground.mode == 'Manual' else 'Simulate feedback')
        if submitted:
            playground.submit(revision, video_id, ratio, liked, immediate_pass)
            st.rerun()


def show_analysis(playground):
    with st.expander('Pairwise pool overlap'):
        st.dataframe([{'Pools': f'{left} / {right}', 'Shared videos': count}
                      for (left, right), count in playground.current.pairwise_overlap().items()],
                     hide_index=True)
    with st.expander('Previous vs updated pools', expanded=bool(playground.previous)):
        if playground.previous is None:
            st.caption('Submit feedback to compare consecutive rankings.')
        else:
            for name, previous, current, tab in zip(POOL_ORDER, playground.previous.pools,
                                                     playground.current.pools, st.tabs(POOL_ORDER)):
                before, after = previous.candidates, current.candidates
                tab.caption(f'{len({x.video_id for x in before} & {x.video_id for x in after})} IDs retained')
                tab.dataframe([
                    {'Rank': rank + 1,
                     'Previous': before[rank].video_id if rank < len(before) else '',
                     'Updated': after[rank].video_id if rank < len(after) else ''}
                    for rank in range(max(len(before), len(after)))
                ], hide_index=True)
    with st.expander('Vector drift and feedback history', expanded=bool(playground.feedback)):
        if playground.feedback:
            st.caption('Euclidean distance from each vector at the start of this session.')
            chart = [{'Interaction': 0, 'STM drift': 0.0, 'LTM drift': 0.0}, *playground.feedback]
            st.line_chart(chart, x='Interaction', y=['STM drift', 'LTM drift'])
            st.dataframe(playground.feedback, hide_index=True)
        else:
            st.caption('Feedback history is empty.')
    with st.expander('Category distribution'):
        scope = st.selectbox('Distribution', ['Catalogue', *POOL_ORDER, 'Session feedback'])
        if scope == 'Catalogue':
            categories = (record.category for record in playground.catalogue.records)
        elif scope == 'Session feedback':
            categories = (row['Category'] for row in playground.feedback)
        else:
            categories = (item.category for item in playground.current.pools[POOL_ORDER.index(scope)].candidates)
        counts = Counter(categories)
        if counts:
            st.bar_chart([{'Category': label, 'Videos': count} for label, count in sorted(counts.items())],
                         x='Category', y='Videos')
        else:
            st.caption('No videos in this view.')


def main():
    st.set_page_config(page_title='Ataraxia Research Playground', layout='wide')
    st.title('Ataraxia Research Playground')
    try:
        catalogue, retriever = catalogue_resources()
    except (DatabaseError, OSError, ValueError) as error:
        st.error(f'Could not load the local catalogue. {error}')
        st.stop()
    categories = sorted({record.category for record in catalogue.records})
    previews = local_previews(tuple(catalogue.video_ids))
    st.caption(f'{len(catalogue.records):,} eligible videos · {len(previews):,} local previews')
    with st.sidebar:
        st.header('Session controls')
        selected = st.multiselect('Onboarding categories', categories, default=categories[:2])
        mode = st.radio('Feedback mode', ['Manual', 'Simulator'])
        profile_seed = int(st.number_input('Simulator profile seed', min_value=0, value=42))
        environment_seed = int(st.number_input('Simulator environment seed', min_value=0, value=73))
        reset = st.button('Reset user', disabled=not selected)
        new_session = st.button('Start new session')
        st.caption('Reset user applies onboarding changes. A new session clears STM and session history while retaining LTM.')
    if 'playground' not in st.session_state or reset:
        if not selected:
            st.info('Select at least one onboarding category.')
            st.stop()
        st.session_state.playground = Playground(catalogue, retriever, selected, mode,
                                                 profile_seed, environment_seed)
    elif new_session:
        st.session_state.playground.new_session(mode, profile_seed, environment_seed)
    playground = st.session_state.playground
    st.caption(f'{playground.mode} feedback · Onboarding: {", ".join(playground.categories)}')
    if playground.simulator_categories:
        st.caption(f'Simulator profile categories: {", ".join(playground.simulator_categories)}. '
                   'The simulator uses its own seeded profile to generate feedback.')
    show_pools(playground)
    show_video_and_feedback(playground, previews)
    show_analysis(playground)


if __name__ == '__main__':
    main()
