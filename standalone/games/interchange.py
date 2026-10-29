"""Check motion JSON, character manifests and preview JSON against the schemas in standalone/schemas.

The checker covers the parts of JSON Schema (2020-12) the bridge's schemas use, so no package is needed.
check_motion adds the rules a schema cannot state, such as parents before children. See docs/INTERCHANGE.md.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from games.space import Space

SCHEMAS = Path(__file__).resolve().parents[1] / 'schemas'
FORMAT = 'sekiro-animation-bridge'
MOTION_VERSIONS = (1, 2)
MANIFEST_VERSIONS = (4, 5)
TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


@lru_cache(maxsize=None)
def schema(name):
    """A schema by file name, such as 'motion.schema.json'."""
    return json.loads((SCHEMAS / name).read_text(encoding='utf-8'))


def _resolve(reference, current):
    target, _, pointer = reference.partition('#')
    document = schema(target) if target else current
    node = document
    for part in filter(None, pointer.split('/')):
        node = node[part]
    return node, document


def _is_type(value, name):
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, TYPES[name])


def _check(value, rule, document, path, found, limit):
    if len(found) >= limit:
        return
    if '$ref' in rule:
        target, target_document = _resolve(rule['$ref'], document)
        _check(value, target, target_document, path, found, limit)
    if 'type' in rule:
        names = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        if not any(_is_type(value, name) for name in names):
            found.append(f'{path or "document"}: expected {" or ".join(names)}, found {type(value).__name__}')
            return
    if 'const' in rule and value != rule['const']:
        found.append(f'{path or "document"}: must be {json.dumps(rule["const"])}')
    if 'enum' in rule and value not in rule['enum']:
        found.append(f'{path or "document"}: must be one of {", ".join(json.dumps(v) for v in rule["enum"])}')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 'minimum' in rule and value < rule['minimum']:
            found.append(f'{path}: must be at least {rule["minimum"]}')
        if 'maximum' in rule and value > rule['maximum']:
            found.append(f'{path}: must be at most {rule["maximum"]}')
        if 'exclusiveMinimum' in rule and value <= rule['exclusiveMinimum']:
            found.append(f'{path}: must be greater than {rule["exclusiveMinimum"]}')
    if isinstance(value, str) and len(value) < rule.get('minLength', 0):
        found.append(f'{path}: must not be empty')
    if isinstance(value, list):
        if len(value) < rule.get('minItems', 0):
            found.append(f'{path}: needs at least {rule["minItems"]} items')
        if len(value) > rule.get('maxItems', len(value)):
            found.append(f'{path}: allows at most {rule["maxItems"]} items')
        if 'items' in rule:
            for index, item in enumerate(value):
                _check(item, rule['items'], document, f'{path}[{index}]', found, limit)
    if isinstance(value, dict):
        for key in rule.get('required', ()):
            if key not in value:
                found.append(f'{path + "." if path else ""}{key}: missing')
        for key, child in rule.get('properties', {}).items():
            if key in value:
                _check(value[key], child, document, f'{path + "." if path else ""}{key}', found, limit)
    if 'anyOf' in rule:
        if not any(not _errors(value, option, document) for option in rule['anyOf']):
            found.append(f'{path or "document"}: matches none of the allowed forms')
    if 'if' in rule:
        branch = rule.get('then') if not _errors(value, rule['if'], document) else rule.get('else')
        if branch:
            _check(value, branch, document, path, found, limit)


def _errors(value, rule, document, limit=1):
    found = []
    _check(value, rule, document, '', found, limit)
    return found


def errors(document, name, limit=20):
    """Problems of a document against a schema, at most limit of them; empty when it is valid."""
    root = schema(name)
    found = []
    _check(document, root, root, '', found, limit)
    return found


def validate(document, name, label=None):
    """Raise ValueError naming the first problems when a document does not match its schema."""
    found = errors(document, name, 5)
    if found:
        raise ValueError(f'{label or name} is not valid: ' + '; '.join(found))
    return document


def check_motion(document, label='Motion JSON'):
    """Check a motion JSON against its schema and the rules between its fields.

    The schema check reads the first and last frames only, so it stays fast for long clips;
    every frame's length is still checked.
    """
    frames = document.get('frames')
    light = dict(document, frames=[frames[0], frames[-1]]) if isinstance(frames, list) and len(frames) > 2 else document
    validate(light, 'motion.schema.json', label)
    bones = document['skeleton']['bones']
    problems = []
    if len(bones) != document['skeleton']['boneCount']:
        problems.append('skeleton.boneCount does not match its bones')
    if document['skeletonName'] != document['skeleton']['name']:
        problems.append('skeletonName does not match skeleton.name')
    for index, bone in enumerate(bones):
        if bone['index'] != index:
            problems.append(f'bone {bone["name"]} has index {bone["index"]} at position {index}')
            break
        if bone['parent'] >= index:
            problems.append(f'bone {bone["name"]} comes before its parent')
            break
    names = [bone['name'] for bone in bones]
    if len(set(names)) != len(names):
        problems.append('bone names repeat')
    tracks = document['trackCount']
    if len(document['trackBoneIndices']) != tracks or len(document['trackNames']) != tracks:
        problems.append('trackBoneIndices and trackNames must each have trackCount entries')
    if any(index >= len(bones) for index in document['trackBoneIndices']):
        problems.append('a track refers to a bone outside the skeleton')
    mapped = [index for index in document['trackBoneIndices'] if index >= 0]
    if len(set(mapped)) != len(mapped):
        problems.append('two tracks animate the same bone')
    if len(frames) != document['frameCount']:
        problems.append('frames does not have frameCount samples')
    if any(len(frame) != tracks for frame in frames):
        problems.append('a frame does not have trackCount samples')
    root = document.get('rootMotion')
    if root is not None and len(root) != document['frameCount']:
        problems.append('rootMotion does not have frameCount samples')
    if 'basis' in document:
        try:
            Space.of(document)
        except ValueError as exc:
            problems.append(str(exc))
    if problems:
        raise ValueError(f'{label} is not valid: ' + '; '.join(problems))
    return document


def check_manifest(document, label='Character manifest'):
    validate(document, 'character.schema.json', label)
    if 'basis' in document:
        Space.of(document)
    return document


def check_preview(document, label='Preview JSON'):
    validate(document, 'preview.schema.json', label)
    count = len(document['bones'])
    if len(document['parents']) != count:
        raise ValueError(f'{label} is not valid: parents must have one entry per bone')
    if any(len(frame) != 3 * count for frame in document['positions']):
        raise ValueError(f'{label} is not valid: each frame needs x, y, z for every bone')
    return document


def motion_space(document):
    """The source space of a motion JSON: its basis, or the FromSoftware space for version 1."""
    return Space.of(document)


def with_source(document, space, engine, game, container, version=None, archive='', member='', index=None):
    """A motion JSON upgraded to version 2: the source it came from and its space."""
    source = dict(engine=engine, game=game, container=container)
    if version is not None:
        source['version'] = version
    if archive:
        source['archive'] = str(archive)
    if member:
        source['member'] = str(member)
    if index is not None:
        source['index'] = int(index)
    return dict(document, formatVersion=2, source=source, **space.to_json())


def readable_motion(document):
    """True when this bridge reads the motion JSON's format and version."""
    return document.get('format') == FORMAT and document.get('formatVersion') in MOTION_VERSIONS
