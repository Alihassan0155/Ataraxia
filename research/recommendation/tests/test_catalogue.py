"""Synthetic fixtures only: no credentials, database, media or inference."""
import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backend.video_data.artifacts import fingerprint
from backend.video_data.catalogue import ORDER, write_package
from research.recommendation.catalogue import EMOTIONS, build_catalogue, load_local_database, load_local_package


def entity(identity, payload, **fields):
    return dict(id=identity, payload=payload, content_hash=fingerprint(payload), **fields)


def fixture():
    data = {t: [] for t in ORDER}
    category = dict(name='Comedy')
    data['interest_categories'] = [entity('category', category, **category)]
    config = dict(extractor={'checkpoint': 'Qwen/test'}, schema_version='v1', extraction_prompt_version='v1')
    frozen = dict(fingerprint='run-fingerprint', config=config, definition_hashes={})
    data['processing_runs'] = [entity('run', {'frozen': frozen}, kind='semantic')]
    # Deliberately unsorted input and orthogonal vectors expose positional joins.
    for vid, position in [('B', 1), ('A', 0)]:
        v = entity('unused', {'video_id': vid}, video_id=vid, title=vid, language='en')
        del v['id']
        data['videos'].append(v)
        ctx = dict(transcript='', acoustic_features={})
        data['video_context'].append(entity('ctx'+vid, ctx, video_id=vid, **ctx))
        affect = dict(video_id=vid, model='gemini-test', valence=.2, arousal=.4,
                      recovery_suitability=.6, confidence=.8,
                      emotions={k: float(k == 'joy') for k in EMOTIONS}, dominant_emotion='joy')
        a = entity('aff'+vid, affect, run_id='run', **affect)
        data['affect_annotations'].append(a)
        emb = dict(checkpoint='BAAI/bge-m3', revision='revision', dimensions=1024)
        sem = dict(primary_category='Comedy', semantic_summary='A video', topics=[], tags=[])
        hashes = {'gemini': a['content_hash']}
        payload = dict(status='complete', video_id=vid, run_fingerprint='run-fingerprint',
                       source_hashes=hashes, source_fingerprint=fingerprint(hashes), definitions={},
                       **config, extracted_at='2026-10-01T00:00:00Z', completed_at='2026-10-01T01:00:00Z',
                       semantic=sem, embedding=emb, template_version='v1', embedding_input_sha256='input')
        data['video_semantics'].append(entity('sem'+vid, payload, video_id=vid, run_id='run',
                                              context_id='ctx'+vid, affect_id='aff'+vid, **sem))
        vector = np.zeros(1024, dtype=np.float32)
        vector[position] = 1
        data['video_embeddings'].append(entity('emb'+vid, emb, video_id=vid, run_id='run',
                                               semantic_id='sem'+vid, model='BAAI/bge-m3', revision='revision',
                                               template_version='v1', input_hash='input', embedding=vector.tolist()))
    return data


def rehash(row):
    row['content_hash'] = fingerprint(row['payload'])


class CatalogueTests(unittest.TestCase):
    def test_alignment_and_read_only_arrays(self):
        data = fixture()
        data['video_embeddings'].reverse()
        result = build_catalogue(data)
        self.assertEqual(result.video_ids.tolist(), ['A', 'B'])
        self.assertEqual(result.embeddings.shape, (2, 1024))
        self.assertEqual(result.affect.shape, (2, 12))
        for i, record in enumerate(result.records):
            self.assertEqual(result.id_to_row[record.video_id], i)
            expected = next(e for e in data['video_embeddings'] if e['id'] == record.embedding_id)
            np.testing.assert_array_equal(result.embeddings[i], expected['embedding'])
        for array in (result.embeddings, result.video_ids, result.affect):
            with self.assertRaises(ValueError):
                array[0] = 0
        with self.assertRaises(TypeError):
            result.id_to_row['A'] = 8

    def test_duplicate_ids_abort(self):
        for table in ('videos', 'video_semantics', 'video_embeddings', 'affect_annotations'):
            with self.subTest(table=table):
                data = fixture()
                data[table].append(copy.deepcopy(data[table][0]))
                with self.assertRaisesRegex(ValueError, 'duplicate primary key'):
                    build_catalogue(data)

    def test_embedding_validation_and_provenance(self):
        mutations = [lambda e: e.update(video_id='A'), lambda e: e.update(run_id='other'),
                     lambda e: e.update(input_hash='wrong'), lambda e: e.update(revision='wrong'),
                     lambda e: e.update(template_version='wrong'),
                     lambda e: e.update(embedding=[0.] * 1023),
                     lambda e: e.update(embedding=[0.] * 1024),
                     lambda e: e.update(embedding=[float('nan')] * 1024),
                     lambda e: e.update(embedding=[float('inf')] * 1024),
                     lambda e: e.update(embedding=[2.] + [0.] * 1023)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = fixture()
                mutate(data['video_embeddings'][0])
                result = build_catalogue(data)
                self.assertEqual(result.video_ids.tolist(), ['A'])
                self.assertEqual(result.report['excluded_records'][0]['video_id'], 'B')

    def test_missing_and_duplicate_embeddings_do_not_fallback(self):
        for duplicate in (False, True):
            data = fixture()
            if duplicate:
                row = copy.deepcopy(data['video_embeddings'][0])
                row['id'] = 'another'
                data['video_embeddings'].append(row)
            else:
                data['video_embeddings'].pop(0)
            self.assertEqual(build_catalogue(data).video_ids.tolist(), ['A'])

    def test_cross_video_affect_and_context(self):
        for field, value in [('affect_id', 'affA'), ('context_id', 'ctxA')]:
            data = fixture()
            data['video_semantics'][0][field] = value
            self.assertEqual(build_catalogue(data).video_ids.tolist(), ['A'])

    def test_affect_ranges_keys_and_sum(self):
        for field, value in [('valence', float('inf')), ('arousal', -1), ('confidence', True),
                             ('recovery_suitability', 2), ('dominant_emotion', 'invalid'),
                             ('emotions', {'joy': 1}), ('emotions', {k: .2 for k in EMOTIONS})]:
            data = fixture()
            a = data['affect_annotations'][0]
            a[field] = value
            a['payload'][field] = value
            # Infinite JSON is itself invalid provenance and fails closed as well.
            if field != 'valence':
                rehash(a)
            result = build_catalogue(data)
            self.assertEqual(result.video_ids.tolist(), ['A'])

    def test_unknown_category_and_missing_semantics(self):
        data = fixture()
        data['video_semantics'][0]['primary_category'] = 'unknown'
        data['video_semantics'][0]['payload']['semantic']['primary_category'] = 'unknown'
        rehash(data['video_semantics'][0])
        self.assertEqual(build_catalogue(data).report['exclusion_reasons'], {'unresolved category assignment': 1})
        data['video_semantics'] = []
        self.assertEqual(build_catalogue(data).embeddings.shape, (0, 1024))
        self.assertEqual(build_catalogue(data).report['exclusion_reasons'], {'missing semantic record': 2})

    def test_payload_hash_and_source_provenance(self):
        for mutation in ('hash', 'source', 'frozen'):
            data = fixture()
            s = data['video_semantics'][0]
            if mutation == 'hash':
                s['content_hash'] = 'wrong'
            elif mutation == 'source':
                s['payload']['source_hashes']['gemini'] = 'wrong'
                s['payload']['source_fingerprint'] = fingerprint(s['payload']['source_hashes'])
                rehash(s)
            else:
                s['payload']['run_fingerprint'] = 'wrong'
                rehash(s)
            self.assertEqual(build_catalogue(data).video_ids.tolist(), ['A'])

    def test_latest_ties_and_newer_incomplete_fail_closed(self):
        for newer in (False, True):
            data = fixture()
            row = copy.deepcopy(data['video_semantics'][0])
            row['id'] = 'new'
            if newer:
                row['payload']['completed_at'] = '2026-10-02T00:00:00Z'
                rehash(row)
            data['video_semantics'].append(row)
            self.assertEqual(build_catalogue(data).video_ids.tolist(), ['A'])

    def test_orphans_reported(self):
        data = fixture()
        data['video_embeddings'][0]['semantic_id'] = 'missing'
        result = build_catalogue(data)
        self.assertEqual(len(result.report['integrity_issues']), 1)
        self.assertEqual(result.video_ids.tolist(), ['A'])

    def test_checksummed_package_round_trip_and_tamper(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'package'
            write_package(path, fixture(), {'kind': 'synthetic-test'})
            result = load_local_package(path)
            self.assertEqual(result.video_ids.tolist(), ['A', 'B'])
            with (path / 'video_embeddings.jsonl').open('a') as file:
                file.write('\n')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                load_local_package(path)

    def test_empty(self):
        result = build_catalogue({})
        self.assertEqual(result.embeddings.shape, (0, 1024))
        self.assertEqual(result.affect.shape, (0, 12))

    def test_database_rejects_connection_strings(self):
        with patch('psycopg.connect') as connect:
            with self.assertRaises(ValueError):
                load_local_database('postgresql://remote/database')
            connect.assert_not_called()

    def test_database_rejects_ambient_remote_routing_before_connect(self):
        for variable in ('PGHOSTADDR', 'PGSERVICE'):
            with patch.dict('os.environ', {variable: 'remote'}), patch('psycopg.connect') as connect:
                with self.assertRaises(ValueError):
                    load_local_database()
                connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
