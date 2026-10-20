"""Validate extracted evidence and render exactly the frozen retrieval template."""
import json
import re
import copy


def normalize_missing(value, schema):
    """Canonicalize blank nullable scalars only; never fill or weaken other fields."""
    value = copy.deepcopy(value)
    changes = []
    for name, rule in schema['properties'].items():
        resolved = schema['$defs'][rule['$ref'].split('/')[-1]] if '$ref' in rule else rule
        types = resolved.get('type', [])
        if (isinstance(types, list) and 'null' in types and
                isinstance(value.get(name), str) and not value[name].strip()):
            value[name] = None
            changes.append(name)
    unsupported = value.get('unsupported_fields')
    if isinstance(unsupported, list):
        for name in changes:
            if name not in unsupported:
                unsupported.append(name)
    return value, changes


def parse(text):
    text = text.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if not lines[-1].strip().startswith('```'):
            raise ValueError('Incomplete JSON fence')
        text = '\n'.join(lines[1:-1])
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Extraction must return one object')
    return value


def validation_feedback(exc):
    """Keep the failing instance path instead of truncating a schema dump."""
    if hasattr(exc, 'absolute_path') and hasattr(exc, 'message'):
        location = '/'.join(str(part) for part in exc.absolute_path) or '<root>'
        return f'{type(exc).__name__} at {location}: {exc.message}'[:1200]
    return f'{type(exc).__name__}: {exc}'[:1200]


def response_errors(value, schema, taxonomy, sources):
    """Report all schema/quote/coverage issues to a bounded repair, not just the first."""
    from jsonschema import Draft202012Validator
    errors = [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(value)]
    if isinstance(value, dict) and isinstance(value.get('field_evidence'), list):
        supported = set()
        for i, entry in enumerate(value['field_evidence']):
            if not isinstance(entry, dict):
                continue
            name, src, quote = entry.get('field'), entry.get('source'), entry.get('quote')
            if isinstance(quote, str) and quote and quote in sources.get(src, ''):
                supported.add(name)
            else:
                errors.append(f'field_evidence/{i}/quote: no exact quote in designated source {src!r} for {name!r}')
        exempt = {'field_evidence', 'unsupported_fields', 'unverified_fields', 'extraction_confidence', 'category_ambiguity'}
        unsupported = value.get('unsupported_fields', [])
        for name, data in value.items():
            if name in exempt:
                continue
            unknown = data is None or data == 'unknown' or data == []
            if not unknown and name not in supported and name not in value.get('unverified_fields', []):
                errors.append(f'{name}: asserted field lacks source evidence')
            if (data is None or data == 'unknown') and isinstance(unsupported, list) and name not in unsupported:
                errors.append(f'{name}: unknown field missing from unsupported_fields')
        primary = value.get('primary_category')
        if primary not in taxonomy['categories']:
            errors.append('primary_category: outside controlled taxonomy')
        secondary = value.get('secondary_categories')
        if isinstance(secondary, list) and any(c not in taxonomy['categories'] for c in secondary if isinstance(c, str)):
            errors.append('secondary_categories: only BROAD taxonomy categories allowed, not subcategories')
    return errors


def validate(value, schema, taxonomy, sources):
    from jsonschema import Draft202012Validator
    Draft202012Validator(schema).validate(value)
    v2 = 'unverified_fields' in schema['properties']
    categories = taxonomy['categories']
    primary = value['primary_category']
    if primary not in categories or any(c not in categories for c in value['secondary_categories']):
        raise ValueError('Category outside frozen taxonomy')
    if value['subcategory'] is not None and value['subcategory'] not in categories[primary]:
        raise ValueError('Subcategory outside primary category taxonomy')
    if primary in value['secondary_categories']:
        raise ValueError('Primary category duplicated as secondary')
    if value['video_format'] not in taxonomy['formats'] or value['content_style'] not in taxonomy['styles']:
        raise ValueError('Format/style outside controlled vocabulary')
    for field, data in value.items():
        if isinstance(data, list) and field != 'field_evidence':
            normalized = [v.casefold().strip() for v in data]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f'Duplicate entries in {field}')
    supported = set()
    for evidence in value['field_evidence']:
        name, source, quote = evidence['field'], evidence['source'], evidence['quote']
        if name not in schema['properties'] or name in ('field_evidence', 'unsupported_fields', 'unverified_fields', 'extraction_confidence', 'category_ambiguity'):
            raise ValueError('Invalid provenance field')
        if quote not in sources.get(source, ''):
            raise ValueError(f'Fabricated/non-verbatim evidence quote: {name}')
        if v2:
            from .provenance import unique_span, CLASSIFICATION, SOURCES, GENERAL
            if unique_span(quote, sources.get(source, '')) is None:
                raise ValueError(f'Ambiguous evidence passage: {name}')
            if name in CLASSIFICATION or source not in SOURCES.get(name, GENERAL):
                raise ValueError(f'Invalid deterministic field/source association: {name}')
            field_value = value[name]
            if quote not in (field_value if isinstance(field_value, list) else [field_value]):
                raise ValueError(f'Evidence is not a deterministic exact field reference: {name}')
        if source == 'acoustic_features' and name not in ('vocal_delivery',):
            raise ValueError('Acoustic statistics cannot support semantic classifications')
        supported.add(name)
    exempt = {'field_evidence', 'unsupported_fields', 'unverified_fields', 'extraction_confidence', 'category_ambiguity'}
    for name, data in value.items():
        if name in exempt:
            continue
        unknown = data is None or data == 'unknown' or data == []
        if not unknown and name not in supported and (not v2 or name not in value['unverified_fields']):
            raise ValueError(f'Missing provenance for {name}')
        if v2 and not unknown and name not in value['unverified_fields']:
            raise ValueError(f'Exact references do not establish verification: {name}')
        if v2 and unknown and name in value['unverified_fields']:
            raise ValueError(f'Unknown field cannot be an unverified assertion: {name}')
        if (data is None or data == 'unknown') and name not in value['unsupported_fields']:
            raise ValueError(f'Unknown field must be explicitly marked unsupported: {name}')
        if not unknown and name in value['unsupported_fields']:
            raise ValueError(f'Unsupported field contains an assertion: {name}')
    if any(name not in schema['properties'] for name in value['unsupported_fields']):
        raise ValueError('Unknown unsupported field name')
    if v2 and any(name not in schema['properties'] or name in exempt for name in value['unverified_fields']):
        raise ValueError('Invalid unverified field name')
    return value


def clean(text):
    return re.sub(r'\s+', ' ', str(text)).strip()


def render(value, job, template):
    sections, seen = [], set()
    def add(label, content):
        if content is None or content == 'unknown' or content == []:
            return
        text = clean('; '.join(content) if isinstance(content, list) else content)
        if text and text.casefold() not in seen:
            sections.append(f'{label}: {text}')
            seen.add(text.casefold())
    for key, label in template['sections']:
        add(label, value[key])
    description = '\n'.join(sections)
    for key, label in template['evidence_sections']:
        add(label, job['sources'][key])
    if template['include_transcript']:
        add('ASR TRANSCRIPT (may contain errors)', job['sources']['transcript'])
    if template['include_original_category']:
        add('ORIGINAL SOURCE CATEGORY (unverified)', job['sources']['original_category'])
    if template['include_title']:
        add('CREATOR TITLE (auxiliary, unverified)', job['sources']['title'])
    if template['include_caption']:
        add('CREATOR CAPTION (auxiliary, unverified)', job['sources']['caption'])
    result = '\n'.join(sections)+'\n'
    if len(description.strip()) < 20:
        raise ValueError('Empty semantic description')
    return description, result
