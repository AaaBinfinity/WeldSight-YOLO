"""Generate polished, automatically paginated WeldSight PDF reports."""

from __future__ import annotations

import html
import io
from collections import Counter
from datetime import datetime
from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as ReportImage,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.annotation_renderer import render_annotated_image
from app.defect_classes import (
    MISSED_DEFECT_REVIEW_DECISIONS,
    canonicalize_record,
    defect_color,
)


PAGE_WIDTH, PAGE_HEIGHT = A4
PAGE_MARGIN = 18 * mm
CONTENT_WIDTH = 174 * mm
NAVY = colors.HexColor('#0D1B2A')
INK = colors.HexColor('#172633')
MUTED = colors.HexColor('#667887')
ACCENT = colors.HexColor('#0097A7')
ACCENT_DARK = colors.HexColor('#007987')
ACCENT_SOFT = colors.HexColor('#E8F7F8')
SURFACE = colors.HexColor('#F5F8FA')
LINE = colors.HexColor('#D9E3E8')
RED = colors.HexColor('#D1434D')
RED_SOFT = colors.HexColor('#FDECEF')
GREEN = colors.HexColor('#16865A')
GREEN_SOFT = colors.HexColor('#EAF7F0')
AMBER = colors.HexColor('#B96B00')
AMBER_SOFT = colors.HexColor('#FFF5DF')
WHITE = colors.white

STATUS_LABELS = {
    'ai_pending': 'AI 后台复核中',
    'completed': '已完成',
    'reviewed': '人工已复核',
    'ai_failed': 'AI 复核失败',
    'queued': '排队中',
    'processing': '处理中',
    'retrying': '正在重试',
    'failed': '失败',
    'not_configured': '未配置',
    'disabled': '已关闭',
    'confirmed': '确认缺陷',
    'false_positive': '确认误报',
    'missed_defect': '确认漏报',
    'mixed': '混合结论',
    'accepted': '结果接受',
    'correct': '结果正确',
    'low': '低风险',
    'medium': '中风险',
    'high': '高风险',
}

DETECTION_REVIEW_LABELS = {
    'confirmed': '确认框正确',
    'false_positive': '排除误报',
    'class_changed': '修改类别',
}


def _register_fonts():
    regular_candidates = (
        Path('C:/Windows/Fonts/msyh.ttc'),
        Path('C:/Windows/Fonts/simhei.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    )
    bold_candidates = (
        Path('C:/Windows/Fonts/msyhbd.ttc'),
        Path('C:/Windows/Fonts/simhei.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'),
    )
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), regular)
    if regular:
        pdfmetrics.registerFont(TTFont('WeldSightCN', str(regular)))
        pdfmetrics.registerFont(TTFont('WeldSightCN-Bold', str(bold)))
        return 'WeldSightCN', 'WeldSightCN-Bold'
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    return 'STSong-Light', 'STSong-Light'


FONT_REGULAR, FONT_BOLD = _register_fonts()


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'ReportTitle',
            parent=base['Title'],
            fontName=FONT_BOLD,
            fontSize=24,
            leading=32,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=3 * mm,
            wordWrap='CJK',
        ),
        'subtitle': ParagraphStyle(
            'ReportSubtitle',
            parent=base['Normal'],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=15,
            textColor=MUTED,
            wordWrap='CJK',
        ),
        'kicker': ParagraphStyle(
            'ReportKicker',
            parent=base['Normal'],
            fontName=FONT_BOLD,
            fontSize=8,
            leading=11,
            textColor=ACCENT_DARK,
            tracking=1.1,
        ),
        'section': ParagraphStyle(
            'ReportSection',
            parent=base['Heading2'],
            fontName=FONT_BOLD,
            fontSize=13.5,
            leading=20,
            textColor=NAVY,
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
            wordWrap='CJK',
        ),
        'body': ParagraphStyle(
            'ReportBody',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=9.6,
            leading=15.5,
            textColor=INK,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'body_bold': ParagraphStyle(
            'ReportBodyBold',
            parent=base['BodyText'],
            fontName=FONT_BOLD,
            fontSize=9.6,
            leading=15.5,
            textColor=INK,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'small': ParagraphStyle(
            'ReportSmall',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=8.2,
            leading=12.5,
            textColor=MUTED,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'table_header': ParagraphStyle(
            'TableHeader',
            parent=base['Normal'],
            fontName=FONT_BOLD,
            fontSize=8.2,
            leading=12,
            textColor=WHITE,
            alignment=TA_LEFT,
            wordWrap='CJK',
        ),
        'table': ParagraphStyle(
            'TableText',
            parent=base['Normal'],
            fontName=FONT_REGULAR,
            fontSize=8.2,
            leading=12.5,
            textColor=INK,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'callout': ParagraphStyle(
            'ReportCallout',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=9.6,
            leading=15.5,
            textColor=INK,
            backColor=ACCENT_SOFT,
            borderColor=colors.HexColor('#BCE5E8'),
            borderWidth=0.7,
            borderPadding=(11, 12, 11, 12),
            borderRadius=4,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'warning': ParagraphStyle(
            'ReportWarning',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=8.6,
            leading=13.5,
            textColor=colors.HexColor('#6D4B13'),
            backColor=AMBER_SOFT,
            borderColor=colors.HexColor('#F0D7A4'),
            borderWidth=0.7,
            borderPadding=(9, 11, 9, 11),
            borderRadius=4,
            wordWrap='CJK',
        ),
        'notes': ParagraphStyle(
            'ReviewNotes',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=9.2,
            leading=15,
            textColor=INK,
            backColor=SURFACE,
            borderColor=LINE,
            borderWidth=0.7,
            borderPadding=(10, 12, 10, 12),
            borderRadius=4,
            wordWrap='CJK',
            splitLongWords=True,
        ),
        'center': ParagraphStyle(
            'ReportCenter',
            parent=base['BodyText'],
            fontName=FONT_REGULAR,
            fontSize=8.6,
            leading=12.5,
            textColor=MUTED,
            alignment=TA_CENTER,
            wordWrap='CJK',
        ),
    }


STYLES = _styles()


def _label(value):
    return STATUS_LABELS.get(str(value or ''), value or '—')


def _safe(value):
    return html.escape(str(value if value not in (None, '') else '—')).replace(
        '\n',
        '<br/>',
    )


def _paragraph(value, style='body'):
    return Paragraph(_safe(value), STYLES[style])


def _format_time(value):
    if not value:
        return '—'
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return str(value)


def _break_token(value, size=16):
    value = str(value or '—')
    return '\n'.join(
        value[index:index + size]
        for index in range(0, len(value), size)
    )


def _compact_multiline(value):
    return '\n'.join(
        line.strip()
        for line in str(value or '').splitlines()
        if line.strip()
    )


def _hex(color):
    return '#{:02X}{:02X}{:02X}'.format(
        round(color.red * 255),
        round(color.green * 255),
        round(color.blue * 255),
    )


def _page_decorator(reference, document_title):
    def draw(canvas, document):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_HEIGHT - 20 * mm, PAGE_WIDTH, 20 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#39D4DC'))
        canvas.setFont(FONT_BOLD, 13)
        canvas.drawString(PAGE_MARGIN, PAGE_HEIGHT - 12.5 * mm, 'WeldSight')
        canvas.setFillColor(colors.HexColor('#D8E6EB'))
        canvas.setFont(FONT_REGULAR, 7.5)
        canvas.drawRightString(
            PAGE_WIDTH - PAGE_MARGIN,
            PAGE_HEIGHT - 12.3 * mm,
            document_title,
        )

        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(PAGE_MARGIN, 15 * mm, PAGE_WIDTH - PAGE_MARGIN, 15 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(FONT_REGULAR, 6.8)
        canvas.drawString(PAGE_MARGIN, 9.5 * mm, f'检测编号：{reference}')
        canvas.drawRightString(
            PAGE_WIDTH - PAGE_MARGIN,
            9.5 * mm,
            f'第 {document.page} 页',
        )
        canvas.restoreState()

    return draw


def _document(output, title, reference):
    return SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=32 * mm,
        bottomMargin=22 * mm,
        title=title,
        author='WeldSight',
        subject='焊缝缺陷智能检测报告',
    ), _page_decorator(reference, title)


def _title_block(title, subtitle, status):
    status_color = GREEN if status in {'已完成', '人工已复核'} else ACCENT
    status_bg = GREEN_SOFT if status in {'已完成', '人工已复核'} else ACCENT_SOFT
    badge = Table(
        [[Paragraph(
            f'<font name="{FONT_BOLD}" color="{_hex(status_color)}">'
            f'{_safe(status)}</font>',
            STYLES['small'],
        )]],
        colWidths=[30 * mm],
    )
    badge.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), status_bg),
        ('BOX', (0, 0), (-1, -1), 0.6, status_color),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROUNDEDCORNERS', [4]),
    ]))
    heading = Table(
        [[
            [
                Paragraph('QUALITY INSPECTION REPORT', STYLES['kicker']),
                Paragraph(_safe(title), STYLES['title']),
                Paragraph(_safe(subtitle), STYLES['subtitle']),
            ],
            badge,
        ]],
        colWidths=[140 * mm, 34 * mm],
    )
    heading.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return [heading, Spacer(1, 6 * mm)]


def _section(title, note=''):
    title_cell = Paragraph(_safe(title), STYLES['section'])
    note_cell = Paragraph(_safe(note), STYLES['small']) if note else ''
    table = Table([[title_cell, note_cell]], colWidths=[122 * mm, 52 * mm])
    table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.8, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return table


def _metadata_table(record, settings):
    rows = [
        (
            '项目名称',
            record.get('project_name')
            or settings.get('project_name')
            or '焊缝质量检测',
            '检测编号',
            _break_token(record['id'].upper()),
        ),
        (
            '检测时间',
            _format_time(record.get('created_at')),
            '样本文件',
            record.get('source_name') or '—',
        ),
        (
            '模型版本',
            f"{record.get('model_version') or 'YOLO'} / "
            f"{record.get('model_name') or '—'}",
            '置信度阈值',
            f"{float(record.get('confidence_threshold') or 0):.2f}",
        ),
        (
            '复核人员',
            record.get('reviewer')
            or settings.get('default_reviewer')
            or '未填写',
            '检测单位',
            settings.get('organization') or '未配置',
        ),
    ]
    data = []
    for row in rows:
        data.append([
            _paragraph(row[0], 'small'),
            _paragraph(row[1], 'table'),
            _paragraph(row[2], 'small'),
            _paragraph(row[3], 'table'),
        ])
    table = Table(
        data,
        colWidths=[22 * mm, 65 * mm, 22 * mm, 65 * mm],
        hAlign='LEFT',
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), SURFACE),
        ('BACKGROUND', (2, 0), (2, -1), SURFACE),
        ('BOX', (0, 0), (-1, -1), 0.7, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table


def _metric_table(items):
    cells = []
    for label, value, color, background in items:
        markup = (
            f'<font name="{FONT_BOLD}" size="17" color="{_hex(color)}">'
            f'{_safe(value)}</font><br/>'
            f'<font name="{FONT_REGULAR}" size="7" color="{_hex(MUTED)}">'
            f'{_safe(label)}</font>'
        )
        cell = Paragraph(markup, STYLES['center'])
        cells.append(cell)
    table = Table([cells], colWidths=[43.5 * mm] * 4)
    commands = [
        ('BOX', (0, 0), (-1, -1), 0.7, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
    ]
    for index, (_, _, _, background) in enumerate(items):
        commands.append(('BACKGROUND', (index, 0), (index, 0), background))
    table.setStyle(TableStyle(commands))
    return table


def _image_flowable(record):
    image = render_annotated_image(
        record.get('original_path'),
        record.get('detections'),
    )
    if image is None:
        image = _load_image(record.get('annotated_path'))
    if image is None:
        placeholder = Table(
            [[_paragraph('检测图不可用', 'body_bold')]],
            colWidths=[CONTENT_WIDTH],
            rowHeights=[68 * mm],
        )
        placeholder.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, -1), WHITE),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return placeholder

    stream = io.BytesIO()
    image.save(stream, format='JPEG', quality=92)
    stream.seek(0)
    width, height = image.size
    max_width = CONTENT_WIDTH
    max_height = 76 * mm
    scale = min(max_width / width, max_height / height)
    flowable = ReportImage(
        stream,
        width=width * scale,
        height=height * scale,
    )
    frame = Table([[flowable]], colWidths=[CONTENT_WIDTH])
    frame.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#263C4C')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return frame


def _load_image(path):
    try:
        return Image.open(path).convert('RGB')
    except Exception:
        return None


def _class_distribution(counts):
    data = [[
        Paragraph('缺陷类别', STYLES['table_header']),
        Paragraph('数量', STYLES['table_header']),
        Paragraph('占比', STYLES['table_header']),
    ]]
    total = max(1, sum(counts.values()))
    for name, count in counts.items():
        color = defect_color(class_name=name)
        class_cell = Paragraph(
            f'<font color="{color}">●</font>&nbsp;&nbsp;{_safe(name)}',
            STYLES['table'],
        )
        data.append([
            class_cell,
            _paragraph(count, 'table'),
            _paragraph(f'{count / total * 100:.1f}%', 'table'),
        ])
    if len(data) == 1:
        data.append([
            _paragraph('未检出候选缺陷', 'table'),
            _paragraph('0', 'table'),
            _paragraph('0.0%', 'table'),
        ])
    table = Table(data, colWidths=[114 * mm, 25 * mm, 35 * mm], repeatRows=1)
    table.setStyle(_standard_table_style())
    return table


def _standard_table_style():
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, SURFACE]),
        ('BOX', (0, 0), (-1, -1), 0.7, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ])


def _detection_table(detections):
    data = [[
        Paragraph('序号', STYLES['table_header']),
        Paragraph('缺陷类别', STYLES['table_header']),
        Paragraph('置信度', STYLES['table_header']),
        Paragraph('检测框坐标', STYLES['table_header']),
    ]]
    for index, item in enumerate(detections, 1):
        name = item.get('class_name') or '未知类别'
        color = item.get('color') or defect_color(
            item.get('class_id'),
            name,
        )
        coordinates = item.get('box_xyxy') or item.get('box') or []
        class_cell = Paragraph(
            f'<font color="{color}">●</font>&nbsp;&nbsp;{_safe(name)}',
            STYLES['table'],
        )
        data.append([
            _paragraph(f'{index:02d}', 'table'),
            class_cell,
            _paragraph(
                f"{float(item.get('confidence') or 0) * 100:.1f}%",
                'table',
            ),
            _paragraph(
                ', '.join(f'{float(value):.1f}' for value in coordinates)
                if coordinates else '—',
                'table',
            ),
        ])
    if len(data) == 1:
        data.append([
            _paragraph('—', 'table'),
            _paragraph('未检出候选缺陷', 'table'),
            _paragraph('—', 'table'),
            _paragraph('—', 'table'),
        ])
    table = LongTable(
        data,
        colWidths=[16 * mm, 65 * mm, 28 * mm, 65 * mm],
        repeatRows=1,
    )
    table.setStyle(_standard_table_style())
    return table


def _finding_paragraph(title, detail, color=ACCENT):
    return Paragraph(
        f'<font color="{_hex(color)}">●</font>&nbsp;&nbsp;'
        f'<font name="{FONT_BOLD}">{_safe(title)}</font>'
        f'&nbsp;&nbsp;{_safe(detail)}',
        STYLES['body'],
    )


def _add_review_sections(story, review):
    story.append(_section('AI 复核摘要', '视觉模型复核结果'))
    story.append(Paragraph(
        _safe(
            review.get('summary')
            or review.get('message')
            or 'AI 未提供复核摘要。'
        ),
        STYLES['callout'],
    ))
    story.append(Spacer(1, 5 * mm))

    groups = [
        (
            '确认发现',
            review.get('confirmed_findings') or [],
            lambda item: item.get('class_name') or '候选缺陷',
            lambda item: item.get('reason') or '视觉特征与候选结果一致。',
            GREEN,
            '未报告新增确认缺陷。',
        ),
        (
            '疑似误报',
            review.get('possible_false_positives') or [],
            lambda item: item.get('class_name') or '候选缺陷',
            lambda item: item.get('reason') or '需要人工复核。',
            AMBER,
            '未报告疑似误报。',
        ),
        (
            'AI 可能漏检',
            review.get('possible_missed_defects') or [],
            lambda item: item.get('suspected_type') or '未知类型',
            lambda item: '；'.join(filter(None, [
                item.get('location_description'),
                item.get('reason'),
            ])) or '需要人工复核。',
            RED,
            'AI 未报告可能漏检。',
        ),
    ]
    for group_title, items, title_fn, detail_fn, color, empty in groups:
        story.append(_section(group_title))
        if items:
            for item in items:
                story.append(_finding_paragraph(
                    title_fn(item),
                    detail_fn(item),
                    color,
                ))
                story.append(Spacer(1, 2.5 * mm))
        else:
            story.append(_paragraph(empty, 'small'))

    story.append(_section('处置建议'))
    recommendations = review.get('recommendations') or []
    if recommendations:
        for index, recommendation in enumerate(recommendations, 1):
            story.append(_finding_paragraph(
                f'建议 {index}',
                recommendation,
                ACCENT,
            ))
            story.append(Spacer(1, 2.5 * mm))
    else:
        story.append(_paragraph(
            '请结合原始底片、检测标准和现场工艺进行人工复核。',
        ))


def _human_review(story, record, settings):
    story.append(_section('人工复核记录', '最终结论以人工签署为准'))
    table = Table(
        [[
            _paragraph('人工结论', 'small'),
            _paragraph(_label(record.get('review_decision') or '待复核'), 'table'),
            _paragraph('复核人员', 'small'),
            _paragraph(
                record.get('reviewer')
                or settings.get('default_reviewer')
                or '未填写',
                'table',
            ),
            _paragraph('复核时间', 'small'),
            _paragraph(_format_time(record.get('reviewed_at')), 'table'),
        ]],
        colWidths=[
            20 * mm, 31 * mm,
            20 * mm, 29 * mm,
            20 * mm, 54 * mm,
        ],
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), SURFACE),
        ('BACKGROUND', (2, 0), (2, 0), SURFACE),
        ('BACKGROUND', (4, 0), (4, 0), SURFACE),
        ('BOX', (0, 0), (-1, -1), 0.7, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    review_decision = record.get('review_decision') or ''
    missed_defects_allowed = (
        review_decision in MISSED_DEFECT_REVIEW_DECISIONS
    )
    missed_defects = (
        record.get('missed_defects') or []
        if missed_defects_allowed
        else []
    )
    story.append(_section(
        '人工漏检登记',
        (
            f'检测历史页面已登记 {len(missed_defects)} 项'
            if missed_defects_allowed
            else '仅适用于确认漏报或混合结论'
        ),
    ))
    if not missed_defects_allowed:
        story.append(Paragraph(
            (
                f'当前人工结论（{_safe(_label(review_decision))}）'
                '不包含漏检登记。'
            ),
            STYLES['callout'],
        ))
    elif missed_defects:
        missed_data = [[
            Paragraph('序号', STYLES['table_header']),
            Paragraph('漏检类别', STYLES['table_header']),
        ]]
        for index, item in enumerate(missed_defects, 1):
            class_name = item.get('suspected_type') or '未知类别'
            class_color = item.get('color') or defect_color(
                item.get('class_id'),
                class_name,
            )
            missed_data.append([
                _paragraph(f'{index:02d}', 'table'),
                Paragraph(
                    f'<font color="{class_color}">●</font>&nbsp;&nbsp;'
                    f'{_safe(class_name)}',
                    STYLES['table'],
                ),
            ])
        missed_table = LongTable(
            missed_data,
            colWidths=[24 * mm, 150 * mm],
            repeatRows=1,
        )
        missed_table.setStyle(_standard_table_style())
        story.append(missed_table)
    else:
        story.append(Paragraph(
            '未登记人工漏检类别。',
            STYLES['callout'],
        ))

    story.append(Spacer(1, 5 * mm))
    story.append(_paragraph('复核意见与处置说明', 'body_bold'))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        _safe(
            _compact_multiline(record.get('review_notes'))
            or '暂无人工复核意见。'
        ),
        STYLES['notes'],
    ))

    payload = record.get('corrections') or []
    corrections = payload.get('corrections', []) if isinstance(payload, dict) else payload
    detections = record.get('detections') or []
    story.append(Spacer(1, 4 * mm))
    story.append(_section(
        '已检出框逐项复核',
        f'YOLO 共检出 {len(detections)} 个候选框',
    ))
    if corrections:
        data = [[
            Paragraph('检测框', STYLES['table_header']),
            Paragraph('原检测类别', STYLES['table_header']),
            Paragraph('置信度', STYLES['table_header']),
            Paragraph('逐项结论', STYLES['table_header']),
            Paragraph('人工确认类别', STYLES['table_header']),
        ]]
        for correction in corrections:
            detection_index = int(correction.get('detection_index', 0))
            detection = (
                detections[detection_index]
                if 0 <= detection_index < len(detections)
                else {}
            )
            original_class = (
                correction.get('original_class_name')
                or detection.get('class_name')
                or '未知类别'
            )
            review_decision = correction.get('decision')
            if review_decision == 'false_positive':
                reviewed_class = '—（已排除）'
            elif review_decision == 'class_changed':
                reviewed_class = correction.get('class_name') or '—'
            else:
                reviewed_class = original_class
            data.append([
                _paragraph(
                    f"#{detection_index + 1}",
                    'table',
                ),
                _paragraph(original_class, 'table'),
                _paragraph(
                    (
                        f"{float(detection.get('confidence') or 0) * 100:.1f}%"
                        if detection
                        else '—'
                    ),
                    'table',
                ),
                _paragraph(
                    DETECTION_REVIEW_LABELS.get(
                        review_decision,
                        '待复核',
                    ),
                    'table',
                ),
                _paragraph(reviewed_class, 'table'),
            ])
        correction_table = LongTable(
            data,
            colWidths=[
                18 * mm,
                43 * mm,
                24 * mm,
                40 * mm,
                49 * mm,
            ],
            repeatRows=1,
        )
        correction_table.setStyle(_standard_table_style())
        story.append(correction_table)
    elif detections:
        story.append(Paragraph(
            '尚未保存已检出框的逐项复核结果。',
            STYLES['callout'],
        ))
    else:
        story.append(Paragraph(
            '本次检测没有 YOLO 候选框。',
            STYLES['callout'],
        ))


def build_inspection_pdf(record, settings=None):
    record = canonicalize_record(record)
    settings = settings or {}
    output = io.BytesIO()
    document, page_decorator = _document(
        output,
        '焊缝缺陷质检报告',
        record['id'].upper(),
    )
    review = record.get('ai_review') or {}
    counts = record.get('class_counts') or {}
    risk = _label(review.get('risk_level') or '待评估')
    human_status = _label(record.get('review_decision') or '待复核')

    story = []
    story.extend(_title_block(
        '焊缝缺陷质检报告',
        (
            f"{settings.get('organization') or '检测单位未配置'} · "
            f"{_format_time(record.get('created_at'))}"
        ),
        _label(record.get('status')),
    ))
    story.append(_metadata_table(record, settings))
    story.append(Spacer(1, 6 * mm))
    story.append(_metric_table([
        ('候选缺陷', record.get('detection_count', 0), ACCENT_DARK, ACCENT_SOFT),
        ('AI 复核', _label(review.get('status')), GREEN, GREEN_SOFT),
        ('风险等级', risk, RED, RED_SOFT),
        ('人工结论', human_status, AMBER, AMBER_SOFT),
    ]))
    story.append(Spacer(1, 7 * mm))
    story.append(_section('检测标注图', '多色框对应不同缺陷类别'))
    story.append(Spacer(1, 2 * mm))
    story.append(_image_flowable(record))
    story.append(Spacer(1, 3 * mm))
    story.append(_paragraph(
        '标注框颜色仅用于区分类别；框位置和置信度应结合原始底片复核。',
        'small',
    ))
    story.append(PageBreak())

    story.extend(_title_block(
        '检测结果与候选明细',
        f"检测编号：{record['id'].upper()}",
        _label(review.get('status')),
    ))
    story.append(_section('缺陷类别统计', '按候选框数量统计'))
    story.append(_class_distribution(counts))
    story.append(Spacer(1, 5 * mm))
    story.append(_section('综合结论'))
    story.append(Paragraph(
        _safe(record.get('conclusion') or '暂无综合结论。'),
        STYLES['callout'],
    ))
    story.append(Spacer(1, 5 * mm))
    story.append(_section('YOLO 候选缺陷明细', '坐标格式：x1, y1, x2, y2'))
    story.append(_detection_table(record.get('detections') or []))
    story.append(Spacer(1, 6 * mm))
    story.append(_metric_table([
        ('候选缺陷', record.get('detection_count', 0), ACCENT_DARK, ACCENT_SOFT),
        ('最高置信度', (
            f"{max([
                float(item.get('confidence') or 0)
                for item in (record.get('detections') or [{}])
            ]) * 100:.1f}%"
        ), GREEN, GREEN_SOFT),
        ('AI 状态', _label(review.get('status')), ACCENT_DARK, ACCENT_SOFT),
        ('风险等级', risk, RED, RED_SOFT),
    ]))
    story.append(PageBreak())

    story.extend(_title_block(
        'AI 视觉复核意见',
        (
            f"{review.get('model') or 'Kimi Vision'} · "
            '模型结论仅作为人工复核参考'
        ),
        _label(review.get('status')),
    ))
    _add_review_sections(story, review)
    story.append(PageBreak())

    story.extend(_title_block(
        '人工复核与处置',
        '人工结论、漏检登记、处置意见与修正记录',
        human_status,
    ))
    _human_review(story, record, settings)
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(
        _safe(
            record.get('disclaimer')
            or (
                '本报告由算法辅助生成，仅用于筛查和复核参考，不能替代持证'
                '无损检测人员依据适用标准作出的最终评定。'
            )
        ),
        STYLES['warning'],
    ))

    document.build(
        story,
        onFirstPage=page_decorator,
        onLaterPages=page_decorator,
    )
    output.seek(0)
    return output


def _batch_metadata(batch, settings):
    data = [
        [
            _paragraph('批次名称', 'small'),
            _paragraph(batch.get('name') or batch.get('id'), 'table'),
            _paragraph('批次编号', 'small'),
            _paragraph(_break_token(batch.get('id')), 'table'),
        ],
        [
            _paragraph('创建时间', 'small'),
            _paragraph(_format_time(batch.get('created_at')), 'table'),
            _paragraph('更新时间', 'small'),
            _paragraph(_format_time(batch.get('updated_at')), 'table'),
        ],
        [
            _paragraph('处理状态', 'small'),
            _paragraph(_label(batch.get('status')), 'table'),
            _paragraph('检测单位', 'small'),
            _paragraph(settings.get('organization') or '未配置', 'table'),
        ],
    ]
    table = Table(
        data,
        colWidths=[22 * mm, 65 * mm, 22 * mm, 65 * mm],
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), SURFACE),
        ('BACKGROUND', (2, 0), (2, -1), SURFACE),
        ('BOX', (0, 0), (-1, -1), 0.7, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.45, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table


def _batch_records_table(records):
    data = [[
        Paragraph('序号', STYLES['table_header']),
        Paragraph('样本文件', STYLES['table_header']),
        Paragraph('缺陷数', STYLES['table_header']),
        Paragraph('主要类别', STYLES['table_header']),
        Paragraph('AI 状态', STYLES['table_header']),
        Paragraph('人工结论', STYLES['table_header']),
    ]]
    for index, record in enumerate(records, 1):
        classes = '、'.join((record.get('class_counts') or {}).keys()) or '未检出'
        data.append([
            _paragraph(f'{index:02d}', 'table'),
            _paragraph(record.get('source_name') or '—', 'table'),
            _paragraph(record.get('detection_count', 0), 'table'),
            _paragraph(classes, 'table'),
            _paragraph(_label(record.get('ai_status')), 'table'),
            _paragraph(_label(record.get('review_decision') or '待复核'), 'table'),
        ])
    if len(data) == 1:
        data.append([
            _paragraph('—', 'table'),
            _paragraph('暂无检测记录', 'table'),
            _paragraph('0', 'table'),
            _paragraph('—', 'table'),
            _paragraph('—', 'table'),
            _paragraph('—', 'table'),
        ])
    table = LongTable(
        data,
        colWidths=[13 * mm, 43 * mm, 18 * mm, 47 * mm, 26 * mm, 27 * mm],
        repeatRows=1,
    )
    table.setStyle(_standard_table_style())
    return table


def build_batch_pdf(batch, records, settings=None):
    records = [canonicalize_record(record) for record in records]
    settings = settings or {}
    output = io.BytesIO()
    class_counts = Counter()
    for record in records:
        class_counts.update(record.get('class_counts') or {})

    reference = str(batch.get('id') or 'BATCH').upper()
    document, page_decorator = _document(
        output,
        '批量焊缝检测汇总报告',
        reference,
    )
    story = []
    story.extend(_title_block(
        '批量焊缝检测汇总报告',
        (
            f"{settings.get('organization') or '检测单位未配置'} · "
            f"{_format_time(batch.get('updated_at'))}"
        ),
        _label(batch.get('status')),
    ))
    story.append(_batch_metadata(batch, settings))
    story.append(Spacer(1, 7 * mm))
    story.append(_metric_table([
        ('样本总数', batch.get('total', len(records)), ACCENT_DARK, ACCENT_SOFT),
        ('处理完成', batch.get('completed', 0), GREEN, GREEN_SOFT),
        ('处理失败', batch.get('failed', 0), RED, RED_SOFT),
        ('候选缺陷', sum(class_counts.values()), AMBER, AMBER_SOFT),
    ]))
    story.append(Spacer(1, 7 * mm))
    story.append(_section('缺陷类别分布', '按候选框数量统计'))
    story.append(_class_distribution(class_counts))
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(
        (
            f"本批次共包含 {int(batch.get('total', len(records)) or 0)} 个样本，"
            f"已完成 {int(batch.get('completed', 0) or 0)} 个，"
            f"共生成 {sum(class_counts.values())} 个候选缺陷。"
            '详细标注、AI 复核和人工结论请进入对应检测记录查看。'
        ),
        STYLES['callout'],
    ))
    story.append(PageBreak())

    story.extend(_title_block(
        '批量检测明细',
        f"批次编号：{reference}",
        _label(batch.get('status')),
    ))
    story.append(_section('检测明细', f'共 {len(records)} 条记录'))
    story.append(_batch_records_table(records))
    story.append(Spacer(1, 7 * mm))
    story.append(Paragraph(
        '本汇总报告用于批量任务归档。单张样本的标注图、AI 复核意见和人工'
        '处置记录，请在对应检测编号的详细质检报告中查看。',
        STYLES['callout'],
    ))
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        '本报告由算法辅助生成，最终评定应由具备相应资质的人员依据适用标准完成。',
        STYLES['warning'],
    ))

    document.build(
        story,
        onFirstPage=page_decorator,
        onLaterPages=page_decorator,
    )
    output.seek(0)
    return output
