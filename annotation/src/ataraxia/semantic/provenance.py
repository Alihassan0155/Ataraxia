"""Deterministic v2 provenance: exact spans, never inferred entailment.

No model quotes are repaired or reassigned. Field text is looked up independently
in explicitly designated source families. An exact match is a text reference,
not proof that a complete semantic claim follows from the video.
"""
import copy


EXEMPT = {'field_evidence', 'unsupported_fields', 'unverified_fields',
          'extraction_confidence', 'category_ambiguity'}
CLASSIFICATION = {'primary_category', 'subcategory', 'secondary_categories',
                  'video_format', 'content_style'}
SOURCES = {
    'subjects': ('visual',), 'activities': ('visual', 'motion_temporal'),
    'objects': ('visual',), 'setting': ('visual',), 'presentation': ('visual',),
    'temporal_context': ('motion_temporal',), 'music': ('audio',),
    'sound_effects': ('audio',), 'vocal_delivery': ('audio',),
    'spoken_language': ('recorded_language',),
    'speech_summary': ('speech_text', 'transcript'),
    'dialogue_themes': ('speech_text', 'transcript'),
}
GENERAL = ('visual', 'audio', 'speech_text', 'motion_temporal', 'transcript',
           'caption', 'title', 'original_category', 'recorded_language')


def unique_span(text, source):
    """Return ORIGINAL character offsets only for one literal occurrence."""
    if not isinstance(text, str) or not text or not isinstance(source, str):
        return None
    begin = source.find(text)
    if begin < 0 or source.find(text, begin+1) >= 0:
        return None
    return begin, begin+len(text)


def unknown(value):
    return value is None or value == 'unknown' or value == []


def build_provenance(draft, schema, taxonomy, sources, ignore_invalid=False):
    """Preserve semantic values. Only null/unknown means unsupported.

    All asserted fields remain unverified: string matching is not entailment.
    Classification uses frozen taxonomy membership, never taxonomy quotations.
    Legacy mode rejects malformed citations. Practical mode ignores/audits all
    model citations, including malformed entries; the generated deterministic
    evidence remains strictly validated in either mode.
    """
    if not isinstance(draft, dict):
        raise ValueError('Semantic output must be an object')
    result = copy.deepcopy(draft)
    fields = set(schema['properties'])-EXEMPT
    proposed = result.get('field_evidence', [])
    if not isinstance(proposed, list):
        if not ignore_invalid:
            raise ValueError('field_evidence must be an array')
        proposed = [proposed]
    rejected = []
    allowed = set(schema['properties']['field_evidence']['items']['properties']['source']['enum'])
    for index, entry in enumerate(proposed):
        if (not isinstance(entry, dict) or set(entry) != {'field','source','quote'}
                or not all(isinstance(entry[k], str) for k in ('field','source','quote'))):
            if not ignore_invalid:
                raise ValueError(f'Malformed model evidence at index {index}')
            rejected.append({'index':index,'entry':entry,'reason':'ignored_malformed_model_evidence'})
            continue
        field, source, quote = entry['field'], entry['source'], entry['quote']
        if field not in fields:
            if not ignore_invalid:
                raise ValueError(f'Invalid evidence field: {field}')
            rejected.append({'index':index, **entry, 'reason':'ignored_noncontent_evidence'})
            continue
        if source not in allowed:
            why = 'non_observational_taxonomy' if source == 'taxonomy' else 'invalid_source'
        elif not 1 <= len(quote) <= 250:
            why = 'quote_length'
        elif unique_span(quote, sources.get(source, '')) is None:
            why = 'not_exact_or_not_unique'
        else:
            why = 'model_quote_not_authoritative'
        rejected.append({'index':index, **entry, 'reason':why})
    evidence, references, classifications = [], {}, {}
    for field in sorted(fields):
        if field not in result or unknown(result[field]):
            continue  # Missing required keys still fail schema validation.
        value = result[field]
        if field in CLASSIFICATION:
            classifications[field] = {'basis':'frozen_taxonomy_membership_only',
                                      'taxonomy_version':taxonomy['version'],
                                      'value':copy.deepcopy(value), 'observationally_verified':False}
            continue
        values = value if isinstance(value, list) else [value]
        field_refs = []
        for text in values:
            if not isinstance(text, str) or not 1 <= len(text) <= 250:
                continue
            for source in SOURCES.get(field, GENERAL):
                span = unique_span(text, sources.get(source, ''))
                if span is None:
                    continue
                if len(evidence) >= schema['properties']['field_evidence']['maxItems']:
                    break  # Fields remain unverified even when reference capacity is reached.
                evidence.append({'field':field, 'source':source, 'quote':text})
                field_refs.append({'source':source, 'start':span[0], 'end':span[1],
                                   'quote':text, 'basis':'exact_field_text_not_entailment'})
                break  # Never reinterpret or reassign a rejected model citation.
        if field_refs:
            references[field] = field_refs
    result['field_evidence'] = evidence
    result['unsupported_fields'] = sorted(field for field in fields
                                           if field in result and (result[field] is None or result[field] == 'unknown'))
    result['unverified_fields'] = sorted(field for field in fields
                                          if field in result and not unknown(result[field]))
    provenance = {'policy':'deterministic-exact-v1', 'field_references':references,
                  'classification_provenance':classifications,
                  'rejected_model_evidence':rejected,
                  'field_status':{field:('unsupported' if result.get(field) is None or result.get(field) == 'unknown'
                                        else 'absent' if result.get(field) == [] else 'unverified')
                                  for field in sorted(fields) if field in result},
                  'contradiction_check':'not_performed; missing quotations are not contradictions',
                  'support_check':'exact string references only; no semantic entailment verification'}
    return result, provenance


def validate_provenance(value, provenance, schema, taxonomy, sources):
    """Rebuild stable references/statuses when reading cached metadata."""
    expected, computed = build_provenance(value, schema, taxonomy, sources)
    for key in ('field_evidence', 'unsupported_fields', 'unverified_fields'):
        if value[key] != expected[key]:
            raise ValueError(f'Deterministic provenance mismatch: {key}')
    if not isinstance(provenance, dict):
        raise ValueError('Missing deterministic source provenance')
    for key in ('policy', 'field_references', 'classification_provenance',
                'field_status', 'contradiction_check', 'support_check'):
        if provenance.get(key) != computed[key]:
            raise ValueError(f'Deterministic provenance metadata mismatch: {key}')
    if not isinstance(provenance.get('rejected_model_evidence'), list):
        raise ValueError('Missing rejected-citation audit trail')
