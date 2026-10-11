"""Existing agreement/error definitions, reusable without development data."""
import math
import statistics
import numpy as np
EMOTIONS=("joy", "sadness", "anger", "fear_anxiety", "surprise", "disgust", "calm_contentment", "neutral")

def tv_jsd(a, b):
    tv = sum(abs(a[e]-b[e]) for e in EMOTIONS)/2
    jsd = 0.0
    for e in EMOTIONS:
        midpoint = (a[e]+b[e])/2
        for p in (a[e], b[e]):
            if p:
                jsd += .5*p*math.log2(p/midpoint)
    return tv, max(0.0, jsd)


def pearson(x, y):
    if len(x) < 2:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    covariance = sum((a-mx)*(b-my) for a,b in zip(x,y))
    denominator = math.sqrt(sum((a-mx)**2 for a in x)*sum((b-my)**2 for b in y))
    return covariance/denominator if denominator else None


def ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result, i = [0.0]*len(values), 0
    while i < len(ordered):
        j = i+1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for k in ordered[i:j]:
            result[k] = (i+1+j)/2
        i = j
    return result


def scalar_metrics(x,y):
    delta=x-y
    return {'signed_bias':float(np.mean(delta)),'mae':float(np.mean(abs(delta))),
            'rmse':float(np.sqrt(np.mean(delta**2))),'pearson':pearson(x.tolist(),y.tolist()),
            'spearman':pearson(ranks(x.tolist()),ranks(y.tolist()))}


def emotion_distances(x,y):
    return np.array([tv_jsd(dict(zip(EMOTIONS,a)),dict(zip(EMOTIONS,b))) for a,b in zip(x,y)])


