"""Conservative exact-source repairs. Never fuzzy-match words or switch sources."""
import copy
import re


class EvidenceRepairError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('Evidence checks failed: '+ '; '.join(
            f"field_evidence/{i['index']}/quote ({i['field']}, {i['source']}): {i['error']}" for i in issues))


PUNCTUATION = str.maketrans({'\u2018':"'", '\u2019':"'", '\u201c':'"', '\u201d':'"',
                           '\u2013':'-', '\u2014':'-', '\u00a0':' '})
STOP = set('a an the of to in on at by for from with is are was were be been being and or '
           'it its this that these those their his her as has have had uses using through '
           'person speaker video people man woman shows showing describes about'.split())


def canonical(text):
    """Canonical spacing/typographic punctuation with offsets to ORIGINAL text."""
    out, positions = [], []
    for i, char in enumerate(text):
        char = char.translate(PUNCTUATION)
        if char.isspace():
            if out and out[-1] != ' ':
                out.append(' ')
                positions.append(i)
        else:
            out.append(char)
            positions.append(i)
    while out and out[-1] == ' ':
        out.pop()
        positions.pop()
    return ''.join(out), positions


def exact_passage(quote, source):
    if quote in source:
        return quote
    needle, _ = canonical(quote)
    haystack, offsets = canonical(source)
    if not needle:
        return None
    passages = set()
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        passages.add(source[offsets[index]:offsets[index+len(needle)-1]+1])
        start = index+1
    # Different exact spans with the same canonical form are ambiguous.
    return next(iter(passages)) if len(passages) == 1 else None


def words(text):
    return {v.casefold() for v in re.findall(r'[^\W_]+', text, re.UNICODE)
            if len(v) > 2 and v.casefold() not in STOP}


def shorten(quote, field_value, preferred, maximum):
    """Select complete sentences anchored to field text, never an arbitrary crop.

    This is a lexical relevance screen, not proof of semantic entailment. No
    lexical anchors or an overlong indivisible sentence => explicit rejection.
    """
    values = field_value if isinstance(field_value, list) else [field_value]
    anchors = [words(v) for v in values if isinstance(v, str) and words(v)]
    if not anchors:
        return None
    spans = [(m.start(), m.end()) for m in re.finditer(r'[^.!?\n]+(?:[.!?]+|$)', quote)]
    candidates = []
    for i, (begin, _) in enumerate(spans):
        for _, end in spans[i:]:
            candidate = quote[begin:end].strip()
            if len(candidate) > maximum:
                break
            terms = words(candidate)
            # All list values need lexical support in the retained passage.
            if not all(a & terms for a in anchors):
                continue
            union = set().union(*anchors)
            overlap = len(union & terms)
            if overlap < min(2, len(union)):
                continue
            candidates.append((len(candidate) <= preferred, overlap/len(union),
                               -len(candidate), candidate))
    return max(candidates)[-1] if candidates else None


def repair_quotes(value, schema, sources):
    result = copy.deepcopy(value)
    changes, issues = [], []
    entries = result.get('field_evidence')
    if not isinstance(entries, list):
        return result, changes  # Schema validator reports the structural error.
    rule = schema['properties']['field_evidence']['items']['properties']
    allowed = rule['source']['enum']
    maximum = rule['quote']['maxLength']
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        name, source, original = item.get('field'), item.get('source'), item.get('quote')
        if not isinstance(original, str) or not original:
            continue
        if source not in allowed or name not in schema['properties']:
            issues.append({'index':index, 'field':name, 'source':source,
                           'error':'Invalid field/source; automatic source reassignment is forbidden'})
            continue
        passage = exact_passage(original, sources.get(source, ''))
        if passage is None:
            issues.append({'index':index, 'field':name, 'source':source,
                           'error':'No unique exact passage in designated source (no paraphrase/fuzzy/cross-source repair)'})
            continue
        reason = 'spacing_or_typographic_punctuation' if passage != original else None
        if len(passage) > maximum:
            shorter = shorten(passage, result.get(name), min(200, maximum), maximum)
            if shorter is None:
                issues.append({'index':index, 'field':name, 'source':source,
                               'error':'Overlong quote has no safe complete-sentence field-anchored excerpt'})
                continue
            passage = shorter
            reason = 'complete_sentence_excerpt' if reason is None else reason+'+complete_sentence_excerpt'
        if passage != original:
            assert passage in sources[source] and 0 < len(passage) <= maximum
            item['quote'] = passage
            changes.append({'index':index, 'field':name, 'source':source, 'reason':reason,
                            'original_quote':original, 'replacement_quote':passage,
                            'source_start':sources[source].find(passage)})
    if issues:
        raise EvidenceRepairError(issues)
    return result, changes


def passage_catalog(sources, maximum=200):
    """Immutable exact-source sentence/phrase options for a small selector repair."""
    catalog = {}
    for source, text in sources.items():
        if not isinstance(text, str) or not text.strip() or source == 'acoustic_features':
            continue
        spans = [text] if len(text) <= maximum else [m.group().strip() for m in re.finditer(r'[^.!?\n]+(?:[.!?]+|$)', text)]
        for quote in spans:
            if not quote or len(quote) > maximum or quote not in text:
                continue
            if any(e['source'] == source and e['quote'] == quote for e in catalog.values()):
                continue
            catalog[f'p{len(catalog):03d}'] = {'source':source, 'quote':quote}
    return catalog


def materialize_selection(draft, selection, catalog, schema):
    """Decode explicit model choices; no fallback sources, inferred labels or new words."""
    if not isinstance(selection, dict) or set(selection) != {'evidence', 'corrections'}:
        raise ValueError('Repair selector must contain only evidence and corrections')
    if not isinstance(selection['evidence'], list) or not isinstance(selection['corrections'], dict):
        raise ValueError('Invalid selector field types')
    result = copy.deepcopy(draft)
    exempt = {'field_evidence', 'unsupported_fields', 'extraction_confidence', 'category_ambiguity'}
    for name, value in selection['corrections'].items():
        if name not in schema['properties'] or name in exempt:
            raise ValueError(f'Forbidden selector correction: {name}')
        # The model can explicitly retract unsupported claims or correct taxonomy;
        # it cannot generate replacement descriptive text in a quote-repair call.
        if value not in (None, 'unknown', []) and name not in (
                'primary_category', 'subcategory', 'secondary_categories', 'video_format', 'content_style'):
            raise ValueError(f'Selector may only retract unsupported descriptive claims: {name}')
        result[name] = value
    evidence = []
    for item in selection['evidence']:
        if not isinstance(item, dict) or set(item) != {'field', 'passage_id'}:
            raise ValueError('Evidence selection requires exactly field and passage_id')
        name, passage_id = item['field'], item['passage_id']
        if not isinstance(name, str) or name not in schema['properties'] or name in exempt:
            raise ValueError('Invalid selected field')
        if not isinstance(passage_id, str) or passage_id not in catalog:
            raise ValueError('Invented/unknown passage ID')
        evidence.append({'field':name, **catalog[passage_id]})
    result['field_evidence'] = evidence
    result['unsupported_fields'] = [name for name, value in result.items()
                                    if name not in exempt and (value is None or value == 'unknown')]
    return result


def replace_summary(draft, patch, catalog):
    """Allow only an explicit model-written summary with exact catalog evidence."""
    if not isinstance(patch, dict) or set(patch) != {'semantic_summary', 'passage_id'}:
        raise ValueError('Summary repair requires only semantic_summary and passage_id')
    summary, passage = patch['semantic_summary'], patch['passage_id']
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Summary repair must provide a nonempty supported summary')
    if not isinstance(passage, str) or passage not in catalog:
        raise ValueError('Summary repair selected an unknown passage')
    result = copy.deepcopy(draft)
    result['semantic_summary'] = summary
    return result, passage


def materialize_field_passages(draft, decisions, catalog, schema):
    """One explicit support/retraction decision per field; no generated corrections."""
    result = copy.deepcopy(draft)
    exempt = {'field_evidence', 'unsupported_fields', 'extraction_confidence', 'category_ambiguity'}
    fields = set(schema['required'])-exempt
    if not isinstance(decisions, dict) or set(decisions)-fields:
        raise ValueError('Field-passage repair must decide EVERY content field, and no extra fields')
    decisions = copy.deepcopy(decisions)
    for name in fields-set(decisions):
        if name in draft and (draft[name] is None or draft[name] == 'unknown' or draft[name] == []):
            decisions[name] = None  # Already unknown; no positive claim is inferred or removed.
        else:
            raise ValueError(f'Field-passage repair omitted asserted field: {name}')
    evidence = []
    for name, passage_id in decisions.items():
        rule = schema['properties'][name]
        resolved = schema['$defs'][rule['$ref'].split('/')[-1]] if '$ref' in rule else rule
        if isinstance(passage_id, list) and resolved.get('type') != 'array':
            raise ValueError(f'Multiple passage IDs only allowed for list field: {name}')
        if passage_id is None or passage_id == []:
            types = resolved.get('type')
            if types == 'array':
                result[name] = []
            elif isinstance(types, list) and 'null' in types:
                result[name] = None
            elif name in ('primary_category', 'video_format', 'content_style'):
                result[name] = 'unknown'
            else:
                raise ValueError(f'Cannot retract required nonempty field: {name}')
        else:
            ids = passage_id if isinstance(passage_id, list) else [passage_id]
            if any(not isinstance(p, str) or p not in catalog for p in ids):
                raise ValueError(f'Unknown passage ID for {name}')
            if result.get(name) is None or result.get(name) == 'unknown' or result.get(name) == []:
                raise ValueError(f'Unknown field cannot gain content from a passage ID alone: {name}')
            evidence.extend({'field':name, **catalog[p]} for p in ids)
    result['field_evidence'] = evidence
    result['unsupported_fields'] = [n for n in fields if result[n] is None or result[n] == 'unknown']
    return result
