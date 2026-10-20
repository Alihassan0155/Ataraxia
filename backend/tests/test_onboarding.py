"""Pure sampler, service and HTTP contract tests; no external calls."""
import random,unittest
from uuid import uuid4
from unittest.mock import Mock
from fastapi import FastAPI,HTTPException,Header
from fastapi.testclient import TestClient
from backend.onboarding.api import create_router,get_service
from backend.onboarding.repository import InvalidInterests
from backend.onboarding.service import PreferenceService
from backend.onboarding.sampling import balanced_sample,valid_media

BUCKET='test-private-bucket'
CATEGORY={'id':'category-a','name':'Test interest','taxonomy_version':'test-v1'}

def video(n,category='a'):
    return {'video_id':f'FV{n:06}','title':'A','language':'en','duration_seconds':10.,'orientation':'vertical','category_id':category,'category_name':'Test interest','media_uri':f's3://{BUCKET}/videos/finevideo/FV{n:06}.mp4','availability':'s3_verified'}

class SamplingTests(unittest.TestCase):
    def test_balanced_and_unique(self):
        rows=balanced_sample({'a':[video(n) for n in range(100)],'b':[video(n,'b') for n in range(100,200)]},rng=random.Random(1))
        self.assertEqual(len(rows),50);self.assertEqual(len({r['video_id'] for r in rows}),50)
        self.assertEqual(sum(r['category_id']=='a' for r in rows),25)
    def test_redistributes_insufficient_category(self):
        rows=balanced_sample({'a':[video(n) for n in range(3)],'b':[video(n,'b') for n in range(3,100)]},rng=random.Random(2))
        self.assertEqual(len(rows),50);self.assertEqual(sum(r['category_id']=='a' for r in rows),3)
    def test_overlapping_pools_no_duplicates(self):
        rows=balanced_sample({'a':[video(n) for n in range(6)],'b':[video(n) for n in range(6)]})
        self.assertEqual(len(rows),6)
    def test_empty_and_insufficient(self):
        self.assertEqual(balanced_sample({}),[]);self.assertEqual(len(balanced_sample({'a':[video(1)]})),1)
    def test_randomness_changes_candidates(self):
        groups={'a':[video(n) for n in range(100)]}
        self.assertNotEqual(balanced_sample(groups,rng=random.Random(1)),balanced_sample(groups,rng=random.Random(2)))
    def test_media_rejects_unavailable_other_bucket_and_traversal(self):
        self.assertTrue(valid_media(video(1)['media_uri'],'s3_verified',BUCKET))
        for uri,status in [('s3://other/videos/finevideo/FV000001.mp4','s3_verified'),(video(1)['media_uri'],'local_reference_only'),('s3://'+BUCKET+'/videos/../secret','s3_verified'),('', 's3_verified')]:self.assertFalse(valid_media(uri,status,BUCKET))

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.uid=str(uuid4());self.repo=Mock();self.repo.interests.return_value=[CATEGORY];self.repo.preferences.return_value=[CATEGORY];self.repo.replace.return_value=[CATEGORY]
        def authenticated(authorization:str|None=Header(default=None)):
            if authorization!='Bearer valid':raise HTTPException(401,'Invalid token')
            return {'id':self.uid}
        app=FastAPI();app.include_router(create_router(authenticated));app.dependency_overrides[get_service]=lambda:PreferenceService(self.repo,BUCKET,random.Random(1));self.client=TestClient(app);self.headers={'Authorization':'Bearer valid'}
    def test_public_interests_and_stable_response(self):
        response=self.client.get('/onboarding/interests');self.assertEqual(response.status_code,200);self.assertEqual(response.json(),{'interests':[CATEGORY]})
        self.assertNotIn('server-timing', response.headers)

    def test_auth_required_for_all_user_routes(self):
        for method,path in [('get','/users/me/interests'),('put','/users/me/interests'),('get','/recommendations/cold-start')]:
            self.assertEqual(getattr(self.client,method)(path).status_code,401)
    def test_replace_multiple_and_derive_identity_from_token(self):
        response=self.client.put('/users/me/interests',headers=self.headers,json={'category_ids':['a','b']});self.assertEqual(response.status_code,200)
        args=self.repo.replace.call_args.args;self.assertEqual(str(args[0]),self.uid);self.assertEqual(args[1],['a','b'])
    def test_reject_duplicates_and_user_id_injection(self):
        for body in [{'category_ids':['a','a']},{'category_ids':['a'],'user_id':str(uuid4())}]:self.assertEqual(self.client.put('/users/me/interests',headers=self.headers,json=body).status_code,422)
        self.repo.replace.assert_not_called()
    def test_invalid_unknown_error(self):
        self.repo.replace.side_effect=InvalidInterests('Not selectable')
        self.assertEqual(self.client.put('/users/me/interests',headers=self.headers,json={'category_ids':['unknown']}).status_code,422)
    def test_empty_rejected_without_changing_preferences_and_get_uses_authenticated_user(self):
        self.assertEqual(self.client.put('/users/me/interests',headers=self.headers,json={'category_ids':[]}).status_code,422)
        self.repo.replace.assert_not_called()
        self.client.get('/users/me/interests',headers=self.headers);self.assertEqual(str(self.repo.preferences.call_args.args[0]),self.uid)
    def test_empty_preferences_return_no_candidates(self):
        self.repo.candidate_pool.return_value=([],[])
        self.assertEqual(self.client.get('/recommendations/cold-start',headers=self.headers).json()['videos'],[])
    def test_candidate_metadata_only_and_invalid_media_filtered(self):
        good=video(1,'category-a');bad=video(2,'category-a');bad['availability']='missing'
        wrong=video(3,'category-a');wrong['media_uri']=good['media_uri']
        self.repo.candidate_pool.return_value=([CATEGORY],[good,bad,wrong])
        response=self.client.get('/recommendations/cold-start',headers=self.headers);self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['count'],1);self.assertNotIn('media_uri',response.text);self.assertNotIn('playback_url',response.text)
    def test_limit_bounds(self):
        for value in [0,51]:self.assertEqual(self.client.get(f'/recommendations/cold-start?limit={value}',headers=self.headers).status_code,422)
    def test_database_failure_is_sanitized(self):
        self.repo.interests.side_effect=RuntimeError('secret connection string')
        response=self.client.get('/onboarding/interests');self.assertEqual(response.status_code,503);self.assertNotIn('secret',response.text)
        self.repo.replace.side_effect=RuntimeError('secret')
        self.assertEqual(self.client.put('/users/me/interests',headers=self.headers,json={'category_ids':['category-a']}).status_code,503)

class MainAuthIntegrationTests(unittest.TestCase):
    def test_existing_supabase_dependency_protects_new_routes(self):
        import importlib,os,sys
        from types import SimpleNamespace
        from unittest.mock import patch
        import supabase,boto3
        uid=str(uuid4());auth=Mock()
        auth.auth.get_user.side_effect=lambda token:SimpleNamespace(user=SimpleNamespace(id=uid,email='test@example.org') if token=='valid-jwt' else None)
        auth.auth.sign_in_with_password.return_value=SimpleNamespace(user=SimpleNamespace(id=uid,email='test@example.org'),session=SimpleNamespace(access_token='fixture-access',refresh_token='fixture-refresh'))
        repo=Mock();repo.preferences.return_value=[]
        previous=sys.modules.pop('backend.main',None)
        try:
            with patch.object(supabase,'create_client',return_value=auth),patch.object(boto3,'client',return_value=Mock()),patch.dict(os.environ,{'SUPABASE_URL':'https://test.supabase.co','SUPABASE_KEY':'not-a-real-key','AWS_REGION':'ap-south-1','S3_BUCKET_NAME':BUCKET}):
                main=importlib.import_module('backend.main')
                main.app.dependency_overrides[get_service]=lambda:PreferenceService(repo,BUCKET)
                with TestClient(main.app) as client:
                    self.assertEqual(client.get('/users/me/interests',headers={'Authorization':'Bearer invalid'}).status_code,401)
                    response=client.get('/users/me/interests',headers={'Authorization':'Bearer valid-jwt'})
                    self.assertEqual(response.status_code,200)



                    response=client.post('/auth/login',json={'email':'test@example.org','password':'fixture-password'})
                    self.assertEqual(response.status_code,200)


                    self.assertEqual(response.headers['cache-control'],'no-store')
                    self.assertEqual(str(repo.preferences.call_args.args[0]),uid)
                    self.assertEqual(client.get('/users/me/interests').status_code,401)
                    self.assertEqual(client.get('/health').status_code,200)
                main.app.dependency_overrides.clear()
        finally:
            sys.modules.pop('backend.main',None)
            if previous is not None:sys.modules['backend.main']=previous
