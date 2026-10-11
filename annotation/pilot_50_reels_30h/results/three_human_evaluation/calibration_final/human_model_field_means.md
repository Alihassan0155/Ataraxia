# Matched human and raw model means

A = Ghayas; B = Zara; C = Ali. All fields use the same 47 complete numeric/distribution pilot videos as the main calibration report. Two-human pool = (A+B)/2; three-human pool = (A+B+C)/3. This is a retrospective comparison within the active three-human analysis, not a restored two-human reference.

Valence is [-1,1]; arousal/recovery are [0,1]; emotions are probabilities. Raw models are used. Bias = model mean minus pooled-human mean; positive means overprediction.

| Field | Human A | Human B | Human C | Pool 2 | Pool 3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| valence | 0.128 | 0.213 | 0.179 | 0.170 | 0.173 |
| arousal | 0.404 | 0.400 | 0.540 | 0.402 | 0.448 |
| recovery_suitability | 0.472 | 0.502 | 0.498 | 0.487 | 0.491 |
| joy | 0.213 | 0.283 | 0.315 | 0.248 | 0.270 |
| sadness | 0.015 | 0.013 | 0.040 | 0.014 | 0.023 |
| anger | 0.068 | 0.026 | 0.066 | 0.047 | 0.053 |
| fear_anxiety | 0.021 | 0.040 | 0.021 | 0.031 | 0.028 |
| surprise | 0.104 | 0.157 | 0.089 | 0.131 | 0.117 |
| disgust | 0.028 | 0.002 | 0.083 | 0.015 | 0.038 |
| calm_contentment | 0.121 | 0.181 | 0.149 | 0.151 | 0.150 |
| neutral | 0.430 | 0.298 | 0.236 | 0.364 | 0.321 |

Model cells: **mean / bias versus 2 humans / bias versus 3 humans**.

| Field | Gemini | Qwen | InternVL |
| --- | --- | --- | --- |
| valence | 0.376 / +0.206 / +0.203 | 0.498 / +0.328 / +0.325 | 0.306 / +0.136 / +0.133 |
| arousal | 0.421 / +0.019 / -0.027 | 0.482 / +0.080 / +0.034 | 0.630 / +0.228 / +0.182 |
| recovery_suitability | 0.514 / +0.027 / +0.023 | 0.198 / -0.289 / -0.293 | 0.409 / -0.079 / -0.082 |
| joy | 0.349 / +0.101 / +0.079 | 0.466 / +0.218 / +0.196 | 0.314 / +0.066 / +0.044 |
| sadness | 0.011 / -0.003 / -0.011 | 0.030 / +0.016 / +0.007 | 0.057 / +0.044 / +0.035 |
| anger | 0.019 / -0.028 / -0.034 | 0.051 / +0.004 / -0.002 | 0.117 / +0.070 / +0.064 |
| fear_anxiety | 0.031 / -0.000 / +0.003 | 0.036 / +0.005 / +0.009 | 0.065 / +0.034 / +0.037 |
| surprise | 0.084 / -0.047 / -0.033 | 0.104 / -0.027 / -0.013 | 0.189 / +0.059 / +0.072 |
| disgust | 0.015 / +0.000 / -0.023 | 0.021 / +0.006 / -0.016 | 0.056 / +0.041 / +0.019 |
| calm_contentment | 0.241 / +0.090 / +0.090 | 0.017 / -0.134 / -0.133 | 0.109 / -0.043 / -0.042 |
| neutral | 0.251 / -0.113 / -0.071 | 0.274 / -0.089 / -0.047 | 0.093 / -0.271 / -0.229 |

Dominant emotion is categorical and has no numerical mean; its label agreement and frequencies must be compared separately.