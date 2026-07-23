"""Render stored detections with the canonical Chinese defect labels."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.defect_classes import canonicalize_detections, defect_color


FONT_CANDIDATES = (
    Path('C:/Windows/Fonts/msyh.ttc'),
    Path('C:/Windows/Fonts/simhei.ttf'),
    Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
)


def _font(image_width):
    size = max(16, min(32, round(image_width / 52)))
    for path in FONT_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def render_annotated_image(original_path, detections):
    try:
        image = Image.open(original_path).convert('RGB')
    except Exception:
        return None

    draw = ImageDraw.Draw(image)
    font = _font(image.width)
    line_width = max(2, round(image.width / 700))
    padding = max(4, line_width * 2)

    for item in canonicalize_detections(detections):
        coordinates = item.get('box_xyxy') or item.get('box')
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 4:
            continue
        try:
            x1, y1, x2, y2 = [float(value) for value in coordinates]
        except (TypeError, ValueError):
            continue

        label = item['class_name']
        color = defect_color(item.get('class_id'), item.get('class_name'))
        confidence = item.get('confidence')
        if isinstance(confidence, (int, float)):
            label = f'{label} {confidence * 100:.0f}%'

        draw.rectangle(
            (x1, y1, x2, y2),
            outline=color,
            width=line_width,
        )
        text_box = draw.textbbox((0, 0), label, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        label_x = max(0, min(x1, image.width - text_width - padding * 2))
        label_y = max(0, y1 - text_height - padding * 2)
        draw.rectangle(
            (
                label_x,
                label_y,
                label_x + text_width + padding * 2,
                label_y + text_height + padding * 2,
            ),
            fill=color,
        )
        draw.text(
            (label_x + padding, label_y + padding - text_box[1]),
            label,
            fill='white',
            font=font,
        )
    return image
