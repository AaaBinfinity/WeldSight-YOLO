"""Build user-facing weld inspection reports."""

from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4


def build_detection_report(detections, ai_review):
    counts = Counter(item['class_name'] for item in detections)
    ai_status = ai_review.get('status')
    if ai_status == 'completed':
        conclusion = ai_review.get('summary') or 'AI 复核已完成，请结合明细人工确认。'
    elif detections:
        conclusion = 'YOLO 检出候选缺陷；AI 复核不可用，请由专业人员复核。'
    else:
        conclusion = 'YOLO 未检出候选缺陷；AI 复核不可用，不能据此排除缺陷。'

    return {
        'report_id': uuid4().hex,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'yolo': {
            'detection_count': len(detections),
            'class_counts': dict(sorted(counts.items())),
            'detections': detections,
        },
        'ai_review': ai_review,
        'conclusion': conclusion,
        'disclaimer': (
            '本报告由算法辅助生成，仅用于筛查和复核参考，不能替代持证无损检测人员'
            '依据适用标准作出的最终评定。'
        ),
    }
