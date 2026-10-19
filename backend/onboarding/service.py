from .sampling import balanced_sample,valid_media

class PreferenceService:
    def __init__(self,repository,bucket,rng=None):self.repository,self.bucket,self.rng=repository,bucket,rng
    def interests(self):return {'interests':self.repository.interests()}
    def get(self,user_id):return {'interests':self.repository.preferences(user_id)}
    def replace(self,user_id,ids):return {'interests':self.repository.replace(user_id,ids)}
    def candidates(self,user_id,limit=50):
        if not self.bucket:raise RuntimeError('S3 bucket configuration missing')
        selected,rows=self.repository.candidate_pool(user_id);groups={r['id']:[] for r in selected}
        for row in rows:
            if row['category_id'] not in groups or not valid_media(row['media_uri'],row['availability'],self.bucket):continue
            # A valid URI must also refer to this exact stable video identity.
            if row['media_uri'].rsplit('/',1)[-1]!=row['video_id']+'.mp4':continue
            groups[row['category_id']].append({k:row[k] for k in ('video_id','title','language','duration_seconds','orientation','category_id','category_name')})
        candidates=balanced_sample(groups,limit,self.rng)
        return {'videos':candidates,'count':len(candidates),'limit':limit,'strategy':'balanced_random_metadata_v1'}
