"""Unchanged calibration application extracted from the development implementation."""
import numpy as np
LOWER=np.array([-1.,0.,0.]);UPPER=np.ones(3)

def apply_scalar(x,fit,j):
    if fit['method']=='raw':result=x.copy()
    elif fit['method']=='linear':result=fit['slope']*x+fit['intercept']
    else:result=np.interp(x,fit['x_knots'],fit['y_knots'])
    return np.clip(result,LOWER[j],UPPER[j])


def apply_emotion(x,fit):
    corrected=np.clip(x+np.array(fit['offsets']),0,1);total=corrected.sum(axis=1)
    good=total>1e-12
    corrected[good]/=total[good,None]
    corrected[~good]=fit['fallback_distribution']
    return corrected


