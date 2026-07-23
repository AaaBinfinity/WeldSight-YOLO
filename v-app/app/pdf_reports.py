"""Generate printable WeldSight inspection PDFs with the existing Matplotlib stack."""

from __future__ import annotations

import io
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties
from PIL import Image


PAGE_SIZE = (8.27, 11.69)
INK = '#14202b'
MUTED = '#667481'
CYAN = '#008b99'
LINE = '#dce3e8'
RED = '#c13f49'

STATUS_LABELS = {
    'ai_pending': 'AI 后台复核中',
    'completed': '已完成',
    'reviewed': '人工已复核',
    'ai_failed': 'AI 复核失败',
    'queued': '排队中',
    'processing': '处理中',
    'failed': '失败',
    'not_configured': '未配置',
    'disabled': '已关闭',
    'confirmed': '确认缺陷',
    'false_positive': '确认误报',
    'missed_defect': '确认漏报',
    'mixed': '混合结论',
    'accepted': '结果接受',
    'low': '低',
    'medium': '中',
    'high': '高',
}


def _label(value):
    return STATUS_LABELS.get(str(value or ''), value or '—')


def _font(size=10, bold=False):
    candidates = [
        Path('C:/Windows/Fonts/msyh.ttc'),
        Path('C:/Windows/Fonts/simhei.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    ]
    for path in candidates:
        if path.exists():
            return FontProperties(fname=str(path), size=size, weight='bold' if bold else 'normal')
    return FontProperties(size=size, weight='bold' if bold else 'normal')


def _text(fig, x, y, value, size=10, color=INK, bold=False, ha='left'):
    return fig.text(
        x,
        y,
        str(value),
        color=color,
        fontproperties=_font(size, bold),
        ha=ha,
        va='top',
    )


def _wrap(value, width=48):
    value = str(value or '')
    lines = []
    for paragraph in value.splitlines() or ['']:
        lines.extend(textwrap.wrap(paragraph, width=width) or [''])
    return '\n'.join(lines)


def _format_time(value):
    if not value:
        return '—'
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return value


def _page_header(fig, title, subtitle, page_number):
    _text(fig, 0.07, 0.955, 'WeldSight', 16, CYAN, True)
    _text(fig, 0.93, 0.953, '焊缝缺陷智能检测', 9, MUTED, False, 'right')
    fig.lines.append(
        plt.Line2D([0.07, 0.93], [0.925, 0.925], transform=fig.transFigure, color=LINE, linewidth=0.8)
    )
    _text(fig, 0.07, 0.895, title, 20, INK, True)
    _text(fig, 0.07, 0.858, subtitle, 9, MUTED)
    _text(fig, 0.93, 0.035, f'第 {page_number} 页', 8, MUTED, False, 'right')


def _metadata_block(fig, record, settings):
    rows = [
        ('项目名称', record.get('project_name') or settings.get('project_name') or '焊缝质量检测'),
        ('检测编号', record['id'].upper()),
        ('检测时间', _format_time(record.get('created_at'))),
        ('样本文件', record.get('source_name') or '—'),
        ('模型版本', f"{record.get('model_version', 'YOLO')} / {record.get('model_name', '')}"),
        ('置信度阈值', f"{float(record.get('confidence_threshold', 0)):.2f}"),
        ('复核人员', record.get('reviewer') or settings.get('default_reviewer') or '未填写'),
        ('处理状态', _label(record.get('status'))),
    ]
    y = 0.81
    for index, (label, value) in enumerate(rows):
        column = index % 2
        row = index // 2
        x = 0.07 + column * 0.44
        row_y = y - row * 0.044
        _text(fig, x, row_y, label, 8, MUTED)
        _text(fig, x + 0.095, row_y, value, 8.5, INK, True)


def _load_image(path):
    try:
        return Image.open(path).convert('RGB')
    except Exception:
        return None


def build_inspection_pdf(record, settings=None):
    settings = settings or {}
    output = io.BytesIO()
    with PdfPages(output) as pdf:
        fig = plt.figure(figsize=PAGE_SIZE, facecolor='white')
        _page_header(
            fig,
            '焊缝缺陷质检报告',
            f"机构：{settings.get('organization') or '未配置'}",
            1,
        )
        _metadata_block(fig, record, settings)

        image = _load_image(record.get('annotated_path'))
        ax = fig.add_axes([0.07, 0.31, 0.86, 0.30])
        ax.set_facecolor('#0b1117')
        if image:
            ax.imshow(image)
        else:
            ax.text(
                0.5, 0.5, '检测图不可用',
                color='white', ha='center', va='center',
                fontproperties=_font(12, True),
            )
        ax.axis('off')

        _text(fig, 0.07, 0.285, 'YOLO 检测摘要', 12, INK, True)
        _text(
            fig,
            0.07,
            0.255,
            f"候选缺陷：{record.get('detection_count', 0)} 处",
            10,
            CYAN,
            True,
        )
        counts = record.get('class_counts') or {}
        summary = '；'.join(f'{name} {count}' for name, count in counts.items())
        _text(fig, 0.07, 0.225, _wrap(summary or '未检出候选缺陷', 58), 9, MUTED)
        confidence_summary = ' / '.join(
            f"{item.get('class_name', '缺陷')} {float(item.get('confidence', 0)) * 100:.1f}%"
            for item in (record.get('detections') or [])[:8]
        )
        _text(
            fig,
            0.07,
            0.195,
            _wrap(f'置信度明细：{confidence_summary}' if confidence_summary else '置信度明细：—', 62),
            8.5,
            MUTED,
        )
        _text(fig, 0.07, 0.145, '综合结论', 11, INK, True)
        _text(fig, 0.07, 0.115, _wrap(record.get('conclusion') or '暂无结论。', 62), 9, INK)
        _text(fig, 0.07, 0.072, '本报告由算法辅助生成，最终评定应由具备相应资质的人员依据适用标准完成。', 7.5, MUTED)
        pdf.savefig(fig, bbox_inches=None)
        plt.close(fig)

        fig = plt.figure(figsize=PAGE_SIZE, facecolor='white')
        _page_header(fig, 'AI 复核与人工处置', f"检测编号：{record['id'].upper()}", 2)
        review = record.get('ai_review') or {}
        _text(fig, 0.07, 0.82, 'AI 复核状态', 9, MUTED)
        _text(fig, 0.21, 0.82, _label(review.get('status')), 10, CYAN, True)
        _text(fig, 0.51, 0.82, '风险等级', 9, MUTED)
        _text(fig, 0.64, 0.82, _label(review.get('risk_level', '待评估')), 10, RED, True)

        y = 0.76
        sections = [
            ('AI 复核摘要', review.get('summary') or review.get('message') or 'AI 未提供复核摘要。'),
            (
                '复核发现',
                '；'.join(
                    f"{item.get('class_name', '候选缺陷')}：{item.get('reason', '')}"
                    for item in review.get('confirmed_findings', [])
                ) or '无已确认的新增发现。',
            ),
            (
                '疑似误报与漏检',
                '；'.join([
                    *[
                        f"误报 {item.get('class_name', '')}：{item.get('reason', '')}"
                        for item in review.get('possible_false_positives', [])
                    ],
                    *[
                        f"漏检 {item.get('suspected_type', '')}：{item.get('location_description', '')}"
                        for item in review.get('possible_missed_defects', [])
                    ],
                ]) or '未报告疑似误报或漏检。',
            ),
            (
                '处置建议',
                '；'.join(str(item) for item in review.get('recommendations', []))
                or '请结合原始底片和适用标准进行人工复核。',
            ),
        ]
        for title, value in sections:
            _text(fig, 0.07, y, title, 11, INK, True)
            wrapped = _wrap(value, 62)
            _text(fig, 0.07, y - 0.032, wrapped, 9, MUTED)
            y -= max(0.12, 0.035 * (wrapped.count('\n') + 2))

        _text(fig, 0.07, max(y, 0.25), '人工复核', 11, INK, True)
        human_y = max(y - 0.035, 0.215)
        _text(
            fig,
            0.07,
            human_y,
            f"结论：{_label(record.get('review_decision') or '待复核')}    "
            f"复核人：{record.get('reviewer') or settings.get('default_reviewer') or '未填写'}",
            9,
            INK,
        )
        _text(
            fig,
            0.07,
            human_y - 0.045,
            _wrap(record.get('review_notes') or '暂无人工复核意见。', 62),
            9,
            MUTED,
        )
        _text(
            fig,
            0.07,
            0.07,
            record.get('disclaimer') or '本报告仅用于辅助筛查和复核参考。',
            7.5,
            MUTED,
        )
        pdf.savefig(fig, bbox_inches=None)
        plt.close(fig)
    output.seek(0)
    return output


def build_batch_pdf(batch, records, settings=None):
    settings = settings or {}
    output = io.BytesIO()
    class_counts = Counter()
    for record in records:
        class_counts.update(record.get('class_counts') or {})
    with PdfPages(output) as pdf:
        fig = plt.figure(figsize=PAGE_SIZE, facecolor='white')
        _page_header(
            fig,
            '批量焊缝检测汇总报告',
            f"批次：{batch.get('name') or batch['id']}",
            1,
        )
        metrics = [
            ('样本总数', batch.get('total', 0)),
            ('处理完成', batch.get('completed', 0)),
            ('处理失败', batch.get('failed', 0)),
            ('候选缺陷', sum(class_counts.values())),
        ]
        for index, (label, value) in enumerate(metrics):
            x = 0.07 + index * 0.215
            _text(fig, x, 0.82, label, 8, MUTED)
            _text(fig, x, 0.775, value, 20, CYAN if index != 2 else RED, True)

        _text(fig, 0.07, 0.69, '类别分布', 12, INK, True)
        y = 0.65
        for name, value in class_counts.most_common(10):
            _text(fig, 0.07, y, name, 9, INK)
            _text(fig, 0.44, y, value, 9, CYAN, True, 'right')
            fig.lines.append(
                plt.Line2D([0.07, 0.44], [y - 0.012, y - 0.012], transform=fig.transFigure, color=LINE, linewidth=0.6)
            )
            y -= 0.035

        _text(fig, 0.53, 0.69, '检测明细', 12, INK, True)
        y = 0.65
        for index, record in enumerate(records[:14], 1):
            label = f"{index:02d}  {record.get('source_name', '')[:22]}"
            value = f"{record.get('detection_count', 0)} 处 / {_label(record.get('ai_status'))}"
            _text(fig, 0.53, y, label, 8.5, INK)
            _text(fig, 0.93, y, value, 8.5, MUTED, False, 'right')
            y -= 0.035

        _text(fig, 0.07, 0.11, f"生成时间：{_format_time(batch.get('updated_at'))}", 8, MUTED)
        _text(fig, 0.07, 0.075, f"机构：{settings.get('organization') or '未配置'}", 8, MUTED)
        pdf.savefig(fig, bbox_inches=None)
        plt.close(fig)
    output.seek(0)
    return output
