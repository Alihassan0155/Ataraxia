from pathlib import Path
import unittest
from unittest.mock import patch
from backend.video_data.batch_writer import BatchWriter
from backend.video_data.config import DatabaseSettings
from backend.video_data.batch_sync import main


class BatchWriterSafetyTests(unittest.TestCase):
    def test_activation_default_never_launches_a_process(self):
        from backend.video_data.activate_batch_sync import activate
        with patch('subprocess.Popen',side_effect=AssertionError('Must not activate')):
            self.assertEqual(activate()['status'],'disabled_pending_explicit_activation_approval')

    def writer(self):
        return BatchWriter(Path('annotation'),{str(i) for i in range(1140)},DatabaseSettings('unused'),
                           lambda:(_ for _ in ()).throw(AssertionError('Must not connect')))

    def test_scope_must_have_exactly_1140_ids(self):
        with self.assertRaises(ValueError):BatchWriter(Path('annotation'),{'unapproved'},DatabaseSettings('unused'))

    def test_metadata_and_taxonomy_are_never_inserted_or_updated(self):
        writer=self.writer()
        writer._insert(None,{'table':'videos'}, {})
        writer._insert(None,{'table':'interest_categories'}, {})
        self.assertEqual(writer.last_insertions,{})

    def test_corrupted_queue_snapshot_rejected_before_connecting(self):
        writer=self.writer()
        with patch('backend.video_data.batch_writer.Reader'):
            with self.assertRaisesRegex(ValueError,'hash'):
                writer([{'video_id':'0','semantic_id':'s','bundle':'[]','bundle_hash':'wrong'}])

    def test_exact_existing_vector_and_column_comparison(self):
        self.assertTrue(BatchWriter._same({'embedding':[1.,0.],'content_hash':'a'},
                                        {'embedding':'[1,0]','content_hash':'a'}))
        self.assertFalse(BatchWriter._same({'embedding':[1.,0.]},{'embedding':'[0,1]'}))
        self.assertFalse(BatchWriter._same({'content_hash':'a'},{'content_hash':'b'}))

    def test_partial_write_flags_refused_before_any_connection(self):
        with patch('backend.video_data.batch_sync.load_package',side_effect=AssertionError('No package read')):
            with self.assertRaises(SystemExit):
                main(['--queue','unused','--approved-snapshot','unused','--apply'])
