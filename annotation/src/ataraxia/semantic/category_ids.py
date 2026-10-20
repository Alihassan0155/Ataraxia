"""Strict future category IDs and non-mutating legacy category review.

Category membership is not evidence. Secondary promotion requires a trusted,
independent review supplied by the caller, never a model's own evidence claim.
"""
import copy

POLICY = 'canonical-id-v1'


def choices(taxonomy):
    mapping=taxonomy.get('category_ids',{})
    names=set(taxonomy['categories'])
    if (len(mapping)!=19 or set(mapping)!=names or 'unknown' not in mapping or
            len(set(mapping.values()))!=19 or
            any(not isinstance(v,str) or not v for v in mapping.values())):
        raise ValueError('Expected exactly 19 canonical category IDs including unknown')
    # Existing Supabase IDs use this identity. Refuse accidental ID/name drift.
    from .storage import digest
    if any(identifier!=digest([taxonomy['version'],name]) for name,identifier in mapping.items()):
        raise ValueError('Canonical category ID/name identity mismatch')
    return [{'id':mapping[name],'name':name} for name in sorted(mapping)]


def wire_contract(taxonomy, schema):
    allowed=choices(taxonomy)
    wire=copy.deepcopy(schema)
    wire['properties']['primary_category']={'type':'string','enum':[r['id'] for r in allowed]}
    wire['properties']['secondary_categories']={'type':'array','maxItems':0,'items':{'type':'string'}}
    return allowed,wire


def decode_selection(value, taxonomy):
    """Reject labels BEFORE practical normalization can map/fallback invalid values."""
    allowed={r['id']:r['name'] for r in choices(taxonomy)}
    selected=value.get('primary_category')
    if not isinstance(selected,str) or selected not in allowed:
        raise ValueError('primary_category must be exactly one allowed canonical category ID')
    if value.get('secondary_categories')!=[]:
        raise ValueError('Qwen secondary_categories must be empty; evidence review resolves them')
    result=copy.deepcopy(value)
    result['primary_category']=allowed[selected]
    return result,{'policy':POLICY,'id':selected,'name':allowed[selected],
                   'taxonomy_version':taxonomy['version']}


def validate_selection(record, taxonomy):
    selection=record.get('category_selection',{})
    expected=taxonomy['category_ids'].get(record['semantic']['primary_category'])
    choices(taxonomy)
    if selection!={'policy':POLICY,'id':expected,'name':record['semantic']['primary_category'],
                   'taxonomy_version':taxonomy['version']} or expected is None:
        raise ValueError('Stored category ID/name provenance mismatch')
    if record['semantic']['secondary_categories']!=[]:
        raise ValueError('Qwen classification must contain exactly one category')


def map_legacy(label, taxonomy):
    """Exact canonical/known alias/uniquely-owned subcategory mapping; no fuzzy match."""
    from ataraxia.datasets.normalization import MAPPING
    from .normalization import ALIASES,label_key
    rows=choices(taxonomy);by_id={r['id']:r['name'] for r in rows}
    if isinstance(label,str) and label in by_id:
        return {'original':label,'status':'canonical_id','id':label,'name':by_id[label]}
    if not isinstance(label,str) or not label.strip():
        return {'original':label,'status':'missing','id':None,'name':None}
    canonical={label_key(r['name']):r['name'] for r in rows}
    name=canonical.get(label_key(label))
    candidates=set()
    if name:candidates.add(name)
    else:
        for known,target in {**ALIASES,**MAPPING}.items():
            if label_key(known)==label_key(label) and target in taxonomy['categories']:
                candidates.add(target)
        for parent,subs in taxonomy['categories'].items():
            if any(label_key(sub)==label_key(label) for sub in subs):candidates.add(parent)
    if len(candidates)==1:
        name=next(iter(candidates))
        return {'original':label,'status':'canonical_name' if label in taxonomy['categories'] else 'unambiguous_mapping',
                'id':taxonomy['category_ids'][name],'name':name}
    return {'original':label,'status':'ambiguous_review' if candidates else 'unmapped_review','id':None,'name':None}


def supported_secondary(primary, candidate, semantic_id, review, sources):
    """A trusted human attestation plus exact content passage; no model self-approval."""
    if not primary or not candidate or candidate in (primary,'unknown') or not isinstance(review,dict):return False
    if (review.get('method')!='human_evidence_review' or not review.get('reviewer') or
            review.get('semantic_id')!=semantic_id or review.get('category')!=candidate or
            review.get('supports_category') is not True):return False
    source=review.get('source');quote=review.get('quote')
    return (source in ('visual','audio','speech_text','motion_temporal','transcript') and
            isinstance(quote,str) and bool(quote.strip()) and quote in (sources or {}).get(source,''))
