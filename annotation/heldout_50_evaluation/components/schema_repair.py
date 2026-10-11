"""Schema repair and explicitly logged user-authorized normalization fallback."""
import copy
from decimal import Decimal, InvalidOperation
from common_annotation import EmotionScores, extract_json


def normalize_emotion_points(raw):
    """Proportional rescaling, with largest remainders allocating 1,000 cents."""
    keys=list(EmotionScores.model_fields);scores=raw.get('emotions')
    if not isinstance(scores,dict) or set(scores)!=set(keys):raise ValueError('Normalization requires exactly eight emotion scores')
    values={}
    for key in keys:
        value=scores[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('Normalization requires numeric emotion scores')
        number=Decimal(str(value))
        if not number.is_finite() or not 0<=number<=10:raise ValueError('Normalization requires finite scores in [0,10]')
        values[key]=number
    total=sum(values.values(),Decimal(0))
    if total<=0:raise ValueError('Cannot normalize an all-zero emotion distribution')
    if total==10:raise ValueError('Total is already 10; normalization cannot repair other schema errors')
    exact=[values[k]*1000/total for k in keys];cents=[int(v) for v in exact]
    order=sorted(range(8),key=lambda i:(-(exact[i]-cents[i]),i))
    for i in order[:1000-sum(cents)]:cents[i]+=1
    normalized={k:float(Decimal(cents[i])/100) for i,k in enumerate(keys)}
    result=copy.deepcopy(raw);result['emotions']=normalized
    highest=max(cents);maximum=[keys[i] for i,v in enumerate(cents) if v==highest]
    if result.get('dominant_emotion') not in maximum:result['dominant_emotion']=maximum[0]
    audit={'applied':True,'method':'proportional_largest_remainder_1000_cents',
           'original_total':str(total),'original_emotion_points':copy.deepcopy(scores),
           'normalized_emotion_points':normalized,'original_dominant_emotion':raw.get('dominant_emotion'),
           'normalized_dominant_emotion':result.get('dominant_emotion')}
    return result,audit


def emotion_repair_instruction(text,error):
    instruction='Correct only the schema failure and return complete JSON. Keep the original video evidence and rubric. '
    try:
        raw=extract_json(text);scores=raw['emotions']
        values={k:Decimal(str(scores[k])) for k in EmotionScores.model_fields}
        total=sum(values.values(),Decimal(0));residual=Decimal(10)-sum(v for k,v in values.items() if k!='neutral')
        instruction+=f'Your actual emotion total is {total}, not 10.00; the excess is {total-Decimal(10)}. '
        instruction+='Arithmetic check: '+' + '.join(f'{k}={v}' for k,v in values.items())+f' = {total}. '
        if 0<=residual<=10:
            instruction+=f'If you retain the seven non-neutral scores, neutral MUST be {residual}, because those seven sum to {Decimal(10)-residual}. This is an arithmetic option, not a required affect label; you may redistribute points based on the video. '
    except (ValueError,KeyError,TypeError,InvalidOperation):pass
    return instruction+f'Validation error: {error}. All eight numeric scores must be in [0,10], have at most two decimal places, and total EXACTLY 10.00. Compute their sum before responding. The dominant label must match a maximum. Do not normalize or change any scalar score just to fix the total.'
