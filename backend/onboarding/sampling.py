"""Pure category-balanced sampling and private-media eligibility checks."""
import random
import re
from urllib.parse import urlsplit


def valid_media(uri,availability,bucket):
    if availability!='s3_verified' or not bucket or not isinstance(uri,str):return False
    try:
        parsed=urlsplit(uri)
    except ValueError:
        return False
    return (parsed.scheme=='s3' and parsed.netloc==bucket and not parsed.query and not parsed.fragment
            and bool(re.fullmatch(r'/videos/(finevideo/FV[0-9]+|tiktok/TT_[0-9]+)\.mp4',parsed.path)))


def balanced_sample(groups,limit=50,rng=None):
    """Round-robin random sampling; redistribute exhausted-category capacity."""
    if not 1<=limit<=50:raise ValueError('limit must be between 1 and 50')
    rng=rng or random.SystemRandom()
    pools={k:list(v) for k,v in groups.items() if v}
    for pool in pools.values():rng.shuffle(pool)
    selected=[];seen=set()
    while pools and len(selected)<limit:
        categories=list(pools);rng.shuffle(categories)
        for category in categories:
            pool=pools[category]
            while pool and pool[-1]['video_id'] in seen:pool.pop()
            if pool:
                item=pool.pop();seen.add(item['video_id']);selected.append(item)
            if not pool:del pools[category]
            if len(selected)==limit:break
    return selected
