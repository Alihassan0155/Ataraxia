"""Small deterministic cleanup for the practical semantic policy; no GPU calls.

Label similarity is ONLY for controlled category names, never evidence quotes.
Every content/label normalization is returned as an audit event.
"""
import copy
import difflib
import json
import math
import re


def label_key(value):
    return re.sub(r'[^\w]+', ' ', value.casefold().replace('&', ' and ')).strip()


ALIASES = {
    'humor':'Comedy', 'humour':'Comedy', 'funny':'Comedy',
    'comedic':'Comedy', 'comedy and humor':'Comedy',
    'fitness':'Sports & Fitness', 'sports':'Sports & Fitness',
    'science':'Science & Technology', 'technology':'Science & Technology',
    'motivation':'Mental Health & Motivation', 'mental health':'Mental Health & Motivation',
    'lifestyle':'Lifestyle, Vlogs & Relationships', 'vlogs':'Lifestyle, Vlogs & Relationships',
    'travel':'Travel & Adventure', 'animals':'Nature, Animals & Conservation',
    'nature':'Nature, Animals & Conservation', 'music':'Music & Dance',
    'dance':'Music & Dance', 'beauty':'Beauty & Style', 'fashion':'Beauty & Style',
    'religion':'Religion & Spirituality', 'spirituality':'Religion & Spirituality',
    'news':'News, Politics & Social Issues', 'politics':'News, Politics & Social Issues',
    'entertainment':'Entertainment & Animation', 'animation':'Entertainment & Animation',
    'food':'Food & Cooking', 'cooking':'Food & Cooking', 'diy':'DIY, Crafts & Outdoor Hobbies',
    'crafts':'DIY, Crafts & Outdoor Hobbies', 'cars':'Vehicles',
    'unmapped needs review':'unknown', 'other':'unknown', 'n a':'unknown',
}


def match_label(value, allowed, aliases=None):
    if not isinstance(value, str) or not value.strip():
        return None
    key = label_key(value)
    exact = {label_key(item):item for item in allowed}
    if key in exact:
        return exact[key]
    target = (aliases or {}).get(key)
    if target in allowed:
        return target
    # Conservative spelling/near-name cleanup, not open-ended semantic guessing.
    scores = sorted(((difflib.SequenceMatcher(None,key,k).ratio(),v)
                     for k,v in exact.items() if v != 'unknown'), reverse=True)
    if scores and scores[0][0] >= 0.88 and (len(scores)==1 or scores[0][0]-scores[1][0] >= 0.08):
        return scores[0][1]
    return None


def parse_practical(text):
    """Accept fences/BOM/trailing commas. Never invent missing braces or values."""
    text = text.lstrip('\ufeff').strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if len(lines)<3 or lines[-1].strip() != '```':
            raise ValueError('Incomplete JSON fence')
        text = '\n'.join(lines[1:-1])
    chars, quoted, escaped = [], False, False
    for i,char in enumerate(text):
        if quoted:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            chars.append(char)
        elif char == ',' and text[i+1:].lstrip().startswith(('}',']')):
            continue
        else:
            chars.append(char)
    def object_pairs(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    value = json.loads(''.join(chars), object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError('Semantic output must be an object')
    return value


def normalize_semantic(value, schema, taxonomy, summary_fallback=False):
    result = copy.deepcopy(value)
    changes = []
    def change(field, new, reason):
        old = result.get(field)
        if field not in result or old != new:
            changes.append({'field':field,'original':old,'normalized':copy.deepcopy(new),'reason':reason})
            result[field] = new
    for key in list(result):
        if key not in schema['properties']:
            changes.append({'field':key,'original':result.pop(key),'reason':'ignored_extra_key'})
    for key, rule in schema['properties'].items():
        resolved = schema['$defs'][rule['$ref'].split('/')[-1]] if '$ref' in rule else rule
        types = resolved.get('type')
        if key in ('field_evidence','unsupported_fields','unverified_fields'):
            continue  # Provenance owns these, including malformed model evidence.
        if types == 'array':
            data = result.get(key)
            if data is None or data == '':
                change(key, [], 'empty_list')
            elif isinstance(data, str):
                change(key, [data.strip()] if data.strip() else [], 'scalar_to_list')
            if isinstance(result.get(key), list):
                seen, cleaned = set(), []
                for item in result[key]:
                    if isinstance(item,str):
                        item = item.strip()
                        if not item or item.casefold() in seen:
                            continue
                        seen.add(item.casefold())
                    cleaned.append(item)
                change(key, cleaned, 'trim_and_deduplicate_list')
        elif isinstance(types,list) and 'null' in types:
            data = result.get(key)
            if data is None or isinstance(data,str) and data.strip().casefold() in ('','null','none','unknown','n/a'):
                change(key, None, 'empty_nullable_field')
        elif types == 'number' and isinstance(result.get(key), str):
            try:
                number = float(result[key])
                if math.isfinite(number):
                    change(key, number, 'numeric_string')
            except ValueError:
                pass
        elif types == 'boolean' and isinstance(result.get(key), str) and result[key].strip().casefold() in ('true','false'):
            change(key, result[key].strip().casefold()=='true', 'boolean_string')
    categories = taxonomy['categories']
    # A uniquely owned subcategory may be returned as a broad category.
    parents = {}
    for parent, subs in categories.items():
        for sub in subs:
            parents.setdefault(label_key(sub),set()).add(parent)
    def category(data):
        matched = match_label(data, categories, ALIASES)
        if matched:
            return matched
        owners = parents.get(label_key(data),set()) if isinstance(data,str) else set()
        return next(iter(owners)) if len(owners)==1 else 'unknown'
    primary = category(result.get('primary_category'))
    change('primary_category', primary, 'category_mapping_or_fallback')
    if primary == 'unknown' or 'category_ambiguity' not in result:
        change('category_ambiguity', True, 'unknown_or_missing_classification')
    sub = match_label(result.get('subcategory'), categories[primary])
    change('subcategory', sub, 'subcategory_mapping_or_null')
    secondary = []
    for item in result.get('secondary_categories', []):
        mapped = category(item)
        if mapped not in ('unknown',primary) and mapped not in secondary:
            secondary.append(mapped)
    change('secondary_categories', secondary, 'broad_categories_only_deduplicated')
    for field, labels in (('video_format',taxonomy['formats']), ('content_style',taxonomy['styles'])):
        change(field, match_label(result.get(field), labels) or 'unknown', 'controlled_label_mapping_or_fallback')
    if summary_fallback:
        summary = result.get('semantic_summary')
        missing = summary is None or isinstance(summary,str) and summary.strip().casefold() in ('','null','none','unknown','n/a')
        if missing:
            rule = schema['properties']['semantic_summary']
            for source_field in ('speech_summary', 'meaning'):
                candidate = result.get(source_field)
                if not isinstance(candidate,str):
                    continue
                candidate = candidate.strip()
                if (rule['minLength'] <= len(candidate) <= rule['maxLength']
                        and any(char.isalpha() for char in candidate)):
                    change('semantic_summary', candidate, f'semantic_summary_from_{source_field}')
                    break
            else:
                raise ValueError('Missing semantic_summary and no suitable speech_summary or meaning; no text fabricated')
    return result, changes
