"""Canonical weld-defect class labels shared by APIs, UI data, and reports."""

from __future__ import annotations

import copy
import re
from collections import Counter


DEFECT_CLASSES = (
    {
        'id': 0, 'code': '01', 'name': '未焊透加气孔',
        'label': '01-未焊透加气孔', 'color': '#2F7BFF',
    },
    {
        'id': 1, 'code': '02', 'name': '圆缺',
        'label': '02-圆缺', 'color': '#D97706',
    },
    {
        'id': 2, 'code': '03', 'name': '裂纹',
        'label': '03-裂纹', 'color': '#EF3340',
    },
    {
        'id': 3, 'code': '04', 'name': '未焊透',
        'label': '04-未焊透', 'color': '#8B5CF6',
    },
    {
        'id': 4, 'code': '05', 'name': '内凹',
        'label': '05-内凹', 'color': '#00A9B9',
    },
    {
        'id': 5, 'code': '06', 'name': '圆缺（夹钨）',
        'label': '06-圆缺（夹钨）', 'color': '#F97316',
    },
    {
        'id': 6, 'code': '07', 'name': '未熔合',
        'label': '07-未熔合', 'color': '#16A66A',
    },
)

MISSED_DEFECT_REVIEW_DECISIONS = frozenset({
    'missed_defect',
    'mixed',
})
DETECTION_REVIEW_DECISIONS = frozenset({
    'confirmed',
    'false_positive',
    'class_changed',
})

_BY_ID = {item['id']: item for item in DEFECT_CLASSES}
_BY_CODE = {item['code']: item for item in DEFECT_CLASSES}
_DEFECT_LABELS = frozenset(item['label'] for item in DEFECT_CLASSES)
_BY_ALIAS = {}
for item in DEFECT_CLASSES:
    aliases = {
        item['code'],
        str(int(item['code'])),
        item['name'],
        item['label'],
        item['label'].replace('-', '－'),
        item['label'].replace('（', '(').replace('）', ')'),
    }
    for alias in aliases:
        _BY_ALIAS[alias] = item


def defect_label(class_id=None, class_name=None):
    """Return the canonical numbered label while preserving unknown values."""
    if class_id is not None:
        try:
            item = _BY_ID.get(int(class_id))
        except (TypeError, ValueError):
            item = None
        if item:
            return item['label']

    value = str(class_name or '').strip()
    if not value:
        return '未知类别'
    item = _BY_ALIAS.get(value)
    if item:
        return item['label']

    match = re.match(r'^(?:类别\s*)?0?([1-7])(?:\s*[-－—_:：].*)?$', value)
    if match:
        return _BY_CODE[f'0{match.group(1)}']['label']

    keyword_rules = (
        (('气孔',), '01'),
        (('夹钨',), '06'),
        (('圆缺',), '02'),
        (('裂纹',), '03'),
        (('未焊透',), '04'),
        (('内凹',), '05'),
        (('未熔合',), '07'),
    )
    for keywords, code in keyword_rules:
        if any(keyword in value for keyword in keywords):
            return _BY_CODE[code]['label']
    return value


def defect_color(class_id=None, class_name=None):
    """Return the stable display color assigned to a canonical defect class."""
    try:
        item = _BY_ID.get(int(class_id)) if class_id is not None else None
    except (TypeError, ValueError):
        item = None
    if item:
        return item['color']

    label = defect_label(class_name=class_name)
    match = re.match(r'^0?([1-7])(?:\s*[-－—_:：].*)?$', label)
    if match:
        return _BY_CODE[f'0{match.group(1)}']['color']
    return '#00A9B9'


def canonicalize_detections(detections):
    result = []
    for detection in detections or []:
        item = dict(detection)
        item['class_name'] = defect_label(
            item.get('class_id'),
            item.get('class_name'),
        )
        item['color'] = defect_color(
            item.get('class_id'),
            item.get('class_name'),
        )
        result.append(item)
    return result


def canonicalize_class_counts(counts):
    normalized = Counter()
    for name, count in (counts or {}).items():
        normalized[defect_label(class_name=name)] += int(count)
    return dict(sorted(normalized.items()))


def canonicalize_ai_review(review):
    result = copy.deepcopy(review or {})
    for key in ('confirmed_findings', 'possible_false_positives'):
        for item in result.get(key, []) or []:
            item['class_name'] = defect_label(
                item.get('class_id'),
                item.get('class_name'),
            )
    for item in result.get('possible_missed_defects', []) or []:
        item['suspected_type'] = defect_label(
            item.get('class_id'),
            item.get('suspected_type'),
        )
    return result


def canonicalize_corrections(corrections):
    result = []
    for correction in corrections or []:
        if not isinstance(correction, dict):
            continue
        item = dict(correction)
        item['class_name'] = defect_label(class_name=item.get('class_name'))
        if item.get('original_class_name'):
            item['original_class_name'] = defect_label(
                class_name=item.get('original_class_name')
            )
        result.append(item)
    return result


def canonicalize_missed_defects(missed_defects):
    result = []
    for missed in missed_defects or []:
        if not isinstance(missed, dict):
            continue
        item = dict(missed)
        item['suspected_type'] = defect_label(
            item.get('class_id'),
            item.get('suspected_type'),
        )
        result.append(item)
    return result


def validate_missed_defect_selection(decision, missed_defects):
    """Validate whether a human-review decision may contain missed defects."""
    items = missed_defects or []
    if decision == 'missed_defect' and not items:
        return '确认漏报时，请至少选择一个漏检类别。'
    if decision not in MISSED_DEFECT_REVIEW_DECISIONS and items:
        return '当前复核结论不能登记漏检，请选择“确认漏报”或“混合结论”。'
    return ''


def normalize_detection_reviews(detections, corrections):
    """Validate and normalize one human-review row for every YOLO box."""
    detections = canonicalize_detections(detections)
    if len(corrections or []) != len(detections):
        return [], '请完成每个已检出框的逐项复核。'

    normalized = []
    seen = set()
    for correction in corrections or []:
        if not isinstance(correction, dict):
            return [], '逐项复核数据格式错误。'
        try:
            detection_index = int(correction.get('detection_index'))
        except (TypeError, ValueError):
            return [], '逐项复核包含无效的检测框编号。'
        if (
            detection_index < 0
            or detection_index >= len(detections)
            or detection_index in seen
        ):
            return [], '逐项复核包含重复或越界的检测框编号。'
        seen.add(detection_index)

        review_decision = str(correction.get('decision') or '').strip()
        if review_decision not in DETECTION_REVIEW_DECISIONS:
            return [], '请选择有效的逐项复核结论。'

        original_class = detections[detection_index]['class_name']
        reviewed_class = defect_label(
            class_name=correction.get('class_name')
        )
        if review_decision == 'class_changed':
            if reviewed_class not in _DEFECT_LABELS:
                return [], '修改类别时，请选择有效的缺陷类别。'
            if reviewed_class == original_class:
                return [], '修改类别时，新类别不能与原检测类别相同。'
        else:
            reviewed_class = original_class

        normalized.append({
            'detection_index': detection_index,
            'decision': review_decision,
            'original_class_name': original_class,
            'class_name': reviewed_class,
        })

    normalized.sort(key=lambda item: item['detection_index'])
    return normalized, ''


def validate_human_review_consistency(
    decision,
    detection_reviews,
    missed_defects,
):
    """Reject contradictory overall and per-box human-review conclusions."""
    missed_error = validate_missed_defect_selection(
        decision,
        missed_defects,
    )
    if missed_error:
        return missed_error

    item_decisions = {
        item.get('decision')
        for item in detection_reviews or []
    }
    if decision == 'accepted' and item_decisions - {'confirmed'}:
        return '结果接受时，所有已检出框都必须标记为“确认框正确”。'
    if decision == 'confirmed' and 'false_positive' in item_decisions:
        return '确认缺陷不能同时包含误报，请选择“混合结论”。'
    if decision == 'false_positive' and 'false_positive' not in item_decisions:
        return '确认误报时，请至少将一个检测框标记为“排除误报”。'
    if decision == 'missed_defect' and item_decisions - {'confirmed'}:
        return '确认漏报同时包含框修正时，请选择“混合结论”。'
    if decision == 'mixed':
        signals = set(item_decisions)
        if missed_defects:
            signals.add('missed_defect')
        if len(signals) < 2:
            return '混合结论至少需要两种不同的复核结果。'
    return ''


def canonicalize_record(record):
    if not record:
        return record
    result = dict(record)
    result['detections'] = canonicalize_detections(result.get('detections'))
    if result['detections']:
        result['class_counts'] = dict(sorted(Counter(
            item['class_name'] for item in result['detections']
        ).items()))
    else:
        result['class_counts'] = canonicalize_class_counts(
            result.get('class_counts')
        )
    result['ai_review'] = canonicalize_ai_review(result.get('ai_review'))
    review_payload = result.get('corrections')
    if isinstance(review_payload, dict):
        review_payload = dict(review_payload)
        review_payload['corrections'] = canonicalize_corrections(
            review_payload.get('corrections')
        )
        review_payload['missed_defects'] = canonicalize_missed_defects(
            review_payload.get('missed_defects')
        )
        result['corrections'] = review_payload
        result['missed_defects'] = review_payload['missed_defects']
    else:
        result['corrections'] = canonicalize_corrections(review_payload)
        result['missed_defects'] = canonicalize_missed_defects(
            result.get('missed_defects')
        )
    return result
