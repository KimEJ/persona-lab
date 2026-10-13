"""Exact profile tags derived from source lists and occupation, without inference."""

import ast
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


TAG_KINDS = frozenset({'skill', 'interest', 'occupation'})
MAX_TAG_LABEL_CHARS = 200
MAX_TAG_ID_CHARS = 256
MAX_SOURCE_LIST_CHARS = 32768
REGISTRY_PATH = Path(__file__).with_name('tag_registry.json')
TAG_LOCALES = ('ko', 'en', 'ja')


def _label(value):
    if not isinstance(value, str):
        return ''
    label = ' '.join(unicodedata.normalize('NFKC', value).split())
    return label if 0 < len(label) <= MAX_TAG_LABEL_CHARS else ''


def _source_list(value):
    if isinstance(value, str):
        if len(value) > MAX_SOURCE_LIST_CHARS:
            return []
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError, RecursionError):
                return []
    return value if isinstance(value, list) else []


def valid_tag_id(value):
    """Accept portable IDs and exact old source IDs for frozen experiments."""
    if not isinstance(value, str) or len(value) > MAX_TAG_ID_CHARS:
        return False
    kind, separator, label = value.partition(':')
    if kind not in TAG_KINDS or not separator or not label:
        return False
    normalized = ' '.join(unicodedata.normalize('NFKC', label).split()).casefold()
    return label == normalized


def _portable_id(identifier):
    return re.fullmatch(r'(skill|interest|occupation):(concept/[a-z0-9][a-z0-9/_-]*|source/[0-9a-f]{64})', identifier) is not None


def source_tags(raw):
    """Return normalized labels keyed by canonical IDs; never change source rows."""
    tags = {}

    def add(kind, value):
        label = _label(value)
        identifier = f'{kind}:{label.casefold()}'
        if label and len(identifier) <= MAX_TAG_ID_CHARS:
            tags[identifier] = min(tags.get(identifier, label), label)

    for kind, field in (('skill', 'skills_and_expertise_list'),
                        ('interest', 'hobbies_and_interests_list')):
        for value in _source_list(raw.get(field)):
            add(kind, value)
    add('occupation', raw.get('occupation'))
    return tags


def source_tag_id(identifier):
    """Stable identity for an exact source tag, even after registry updates."""
    kind = identifier.partition(':')[0]
    return f'{kind}:source/{hashlib.sha256(identifier.encode("utf-8")).hexdigest()}'


@lru_cache(maxsize=1)
def _registry():
    empty = {'entries': {}, 'sources': {}, 'aliases': {}, 'hashes': {}}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('tags'), list):
        return empty
    entries, source_candidates, alias_candidates = {}, {}, {}

    def candidate(mapping, key, identifier):
        mapping.setdefault(key, set()).add(identifier)

    for value in data['tags']:
        if not isinstance(value, dict):
            continue
        identifier, kind = value.get('id'), value.get('kind')
        if (not valid_tag_id(identifier) or not isinstance(kind, str) or kind not in TAG_KINDS
                or not identifier.startswith(f'{kind}:concept/')
                or not _portable_id(identifier)
                or identifier in entries):
            continue
        source = value.get('source')
        labels = value.get('labels')
        if not isinstance(source, list) or not isinstance(labels, dict):
            continue
        source = sorted({_label(label) for label in source} - {''})
        labels = {locale: _label(labels.get(locale)) for locale in TAG_LOCALES}
        fallback = labels.get('en') or labels.get('ja') or labels.get('ko') or next(iter(source), '')
        if not source or not fallback:
            continue
        labels = {locale: label or fallback for locale, label in labels.items()}
        entries[identifier] = {'id': identifier, 'kind': kind, 'source': source, 'labels': labels}
        for label in source:
            old_id = f'{kind}:{label.casefold()}'
            candidate(source_candidates, old_id, identifier)
            candidate(alias_candidates, old_id, identifier)
        for label in labels.values():
            candidate(alias_candidates, f'{kind}:{label.casefold()}', identifier)
    # Conflicting registry aliases stay unmapped rather than expanding a cohort.
    explicit_sources = {key: next(iter(values)) for key, values in source_candidates.items() if len(values) == 1}
    aliases = {key: next(iter(values)) for key, values in alias_candidates.items() if len(values) == 1}
    # A unique translation is an explicit language alias; exact source labels win
    # over a translation used by another concept. Ambiguous names remain exact.
    sources = {**aliases, **explicit_sources}
    hashes = {source_tag_id(key): identifier for key, identifier in sources.items()}
    return {'entries': entries, 'sources': sources, 'aliases': aliases, 'hashes': hashes}


def canonical_tag_id(identifier):
    """Resolve known language aliases; an unknown source keeps a stable hash."""
    registry = _registry()
    if identifier in registry['entries']:
        return identifier
    if identifier in registry['sources']:
        return registry['sources'][identifier]
    if identifier in registry['hashes']:
        return registry['hashes'][identifier]
    return identifier if _portable_id(identifier) else source_tag_id(identifier)


def persona_tags(raw):
    """Current portable identities with original labels; no inferred source merges."""
    registry = _registry()
    tags = {}
    for identifier, label in source_tags(raw).items():
        canonical = registry['sources'].get(identifier) or source_tag_id(identifier)
        tags[canonical] = min(tags.get(canonical, label), label)
    return tags


def matching_tags(raw):
    """Keep every saved source/hash filter exact while supporting current concepts."""
    registry = _registry()
    available = set()
    for identifier in source_tags(raw):
        available.add(identifier)
        available.add(source_tag_id(identifier))
        if identifier in registry['sources']:
            available.add(registry['sources'][identifier])
    return available


def tag_matches(raw, identifier):
    return identifier in matching_tags(raw)


def tag_source_labels(people, identifiers=None):
    """Recover source labels for saved IDs, optionally retaining only selected IDs."""
    registry = _registry()
    wanted = set(identifiers) if identifiers is not None else None
    if wanted == set():
        return {}
    labels = {}
    for person in people:
        raw = person.raw if hasattr(person, 'raw') else person
        for identifier, label in source_tags(raw).items():
            candidates = {identifier, source_tag_id(identifier)}
            canonical = registry['sources'].get(identifier)
            if canonical:
                candidates.add(canonical)
            for candidate in candidates:
                if wanted is None or candidate in wanted:
                    labels[candidate] = min(labels.get(candidate, label), label)
    return labels


def tag_metadata(identifier, locale='ko', source_label=None):
    """Resolve display labels without rewriting the requested filter identity."""
    registry = _registry()
    kind, _, suffix = identifier.partition(':')
    canonical = (identifier if identifier in registry['entries'] else
                 registry['sources'].get(identifier) or registry['aliases'].get(identifier)
                 or registry['hashes'].get(identifier))
    entry = registry['entries'].get(canonical)
    if entry:
        labels = dict(entry['labels'])
        aliases = list(dict.fromkeys([*entry['source'], *labels.values()]))
    else:
        fallback = _label(source_label)
        if not fallback and not _portable_id(identifier):
            fallback = _label(suffix)
        labels = ({language: fallback for language in TAG_LOCALES} if fallback else
                  {'ko': '태그', 'en': 'Tag', 'ja': 'タグ'})
        aliases = [fallback] if fallback else []
    original = _label(source_label)
    if original and original not in aliases:
        aliases.append(original)
    return {'id': identifier, 'kind': kind, 'label': labels.get(locale, labels['ko']),
            'labels': labels, 'aliases': aliases}


def tag_catalog(people):
    """Canonical metadata counted once per person, ordered by count then identity."""
    counts = {}
    for person in people:
        raw = person.raw if hasattr(person, 'raw') else person
        for identifier, label in persona_tags(raw).items():
            entry = counts.setdefault(identifier, {'source_label': label, 'count': 0})
            entry['source_label'] = min(entry['source_label'], label)
            entry['count'] += 1
    catalog = [{**tag_metadata(identifier, source_label=entry['source_label']), 'count': entry['count']}
               for identifier, entry in counts.items()]
    return sorted(catalog, key=lambda entry: (-entry['count'], entry['id']))
