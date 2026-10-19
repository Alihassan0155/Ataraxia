import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from backend.processing.cli import run_ids,validated_ids,embedding_jobs,process_semantic_batch

class LauncherTests(unittest.TestCase):
    def test_full_catalogues_not_database_subset(self):
        self.assertEqual(len(run_ids('gemini')),4126)
        self.assertEqual(len(run_ids('embedder')),4226)
    def test_invalid_completion_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'annotations.jsonl';p.write_text('\n'.join([json.dumps({'video_id':'A','valid':True}),json.dumps({'video_id':'B'}),json.dumps({'video_id':'OUT','valid':True}),'broken']))
            def validate(row):
                if not row.get('valid'):raise ValueError('invalid')
            self.assertEqual(validated_ids([p],{'A','B'},validate),{'A'})
    def test_embedder_filters_scope_and_waits_for_semantics(self):
        worker=Mock();worker.queue.return_value=([{'video_id':'A'},{'video_id':'B'}],[],[],[])
        worker.recover_metadata.side_effect=[{'semantic':'cached'},None]
        jobs,_,_,_,waiting=embedding_jobs(worker,{'A':{},'B':{},'OUT':{}},{'A','B'})
        self.assertEqual(jobs,[{'video_id':'A'}]);self.assertEqual(waiting,['B'])
        self.assertEqual(set(worker.queue.call_args.args[0]),{'A','B'})
        worker.extract.assert_not_called();worker.embed.assert_not_called()

    def test_combined_batch_extracts_only_missing_then_embeds(self):
        worker=Mock();worker.cfg={'extractor':{'batch_size':1}}
        batch=[{'video_id':'cached'},{'video_id':'missing'}]
        worker.state.side_effect=[{'attempts':2,'status':'metadata_ready'},{'attempts':0,'status':'pending'}]
        worker.recover_metadata.side_effect=[{'semantic':'cached'},None]
        worker.interrupted.return_value=False
        write=Mock()
        process_semantic_batch(worker,batch,write,lambda:'now')
        worker.extract.assert_called_once_with([batch[1]])
        worker.embed.assert_called_once_with(batch)
        self.assertEqual([c.args[1]['attempts'] for c in write.call_args_list],[2,1])
        names=[c[0] for c in worker.mock_calls]
        self.assertLess(names.index('extract'),names.index('embed'))

    def test_corrupt_cache_is_failed_and_interrupt_prevents_inference(self):
        worker=Mock();worker.cfg={'extractor':{'batch_size':1}}
        worker.state.return_value={'attempts':0,'status':'pending'}
        worker.recover_metadata.side_effect=ValueError('invalid hash')
        worker.interrupted.return_value=True
        process_semantic_batch(worker,[{'video_id':'bad'}],Mock(),lambda:'now')
        self.assertEqual(worker.failed.call_args.args[1],'cached_metadata')
        worker.extract.assert_not_called();worker.embed.assert_not_called()
