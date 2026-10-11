"""Matched-cohort human means and raw model biases for the active pilot."""
import csv
import json
import statistics
from build_human_fieldwise_consensus import BASE, EMOTIONS
from build_human_soft_reference import normalize_scalar, write_csv
from compare_pilot_models import SOURCES


def main():
    root=BASE/'pilot_50_reels_30h/results/three_human_evaluation'
    refs=json.loads((root/'reference/human_soft_reference.json').read_text(encoding='utf-8'))['rows']
    refs=[r for r in refs if r['overall_human_uncertainty'] is not None]
    models={m:{r['video_id']:r for r in (json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip())} for m,p in SOURCES.items()}
    rows=[]
    for field in ['valence','arousal','recovery_suitability',*EMOTIONS]:
        scalar=field not in EMOTIONS
        means={h:statistics.mean(normalize_scalar(field,r[f'human_{h}_{field}']) if scalar else r[f'human_{h}_emotion_distribution'][field] for r in refs) for h in ['ghayas','zara','ali']}
        pooled2=(means['ghayas']+means['zara'])/2
        pooled3=sum(means.values())/3
        for model,data in models.items():
            mean=statistics.mean(data[r['video_id']][field] if scalar else data[r['video_id']]['emotions'][field]/sum(data[r['video_id']]['emotions'].values()) for r in refs)
            rows.append({'field':field,'n':len(refs),'human_a_ghayas_mean':means['ghayas'],'human_b_zara_mean':means['zara'],'human_c_ali_mean':means['ali'],
                         'two_human_pooled_mean':pooled2,'three_human_pooled_mean':pooled3,'model':model,'model_mean':mean,
                         'bias_vs_two_humans':mean-pooled2,'bias_vs_three_humans':mean-pooled3})
    write_csv(root/'calibration_final/human_model_field_means.csv',rows)
    lines=['# Matched human and raw model means','',
           f'A = Ghayas; B = Zara; C = Ali. All fields use the same {len(refs)} complete numeric/distribution pilot videos as the main calibration report. Two-human pool = (A+B)/2; three-human pool = (A+B+C)/3. This is a retrospective comparison within the active three-human analysis, not a restored two-human reference.','',
           'Valence is [-1,1]; arousal/recovery are [0,1]; emotions are probabilities. Raw models are used. Bias = model mean minus pooled-human mean; positive means overprediction.','',
           '| Field | Human A | Human B | Human C | Pool 2 | Pool 3 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in rows[::3]:lines.append('| '+r['field']+' | '+' | '.join(f'{r[k]:.3f}' for k in ['human_a_ghayas_mean','human_b_zara_mean','human_c_ali_mean','two_human_pooled_mean','three_human_pooled_mean'])+' |')
    lines+=['','Model cells: **mean / bias versus 2 humans / bias versus 3 humans**.','','| Field | Gemini | Qwen | InternVL |','| --- | --- | --- | --- |']
    for offset in range(0,len(rows),3):
        triple=rows[offset:offset+3]
        lines.append('| '+triple[0]['field']+' | '+' | '.join(f"{r['model_mean']:.3f} / {r['bias_vs_two_humans']:+.3f} / {r['bias_vs_three_humans']:+.3f}" for r in triple)+' |')
    lines+=['','Dominant emotion is categorical and has no numerical mean; its label agreement and frequencies must be compared separately.']
    report='\n'.join(lines)
    (root/'calibration_final/human_model_field_means.md').write_text(report,encoding='utf-8')
    print(report)


if __name__=='__main__':main()
