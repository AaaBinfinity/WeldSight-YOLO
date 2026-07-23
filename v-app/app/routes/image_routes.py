import base64
import io

import cv2
import numpy as np
from PIL import Image
from flask import Response, current_app, jsonify, request

from app.inference import render_detections, run_detections
from app.reporting import build_detection_report
from app.routes import image_bp


def _decode_upload():
    if 'image' not in request.files:
        raise ValueError("未上传图片，请添加 'image' 字段。")
    image_bytes = request.files['image'].read()
    pil_img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


@image_bp.route('/detect_image', methods=['POST'])
def detect_image():
    """Backward-compatible endpoint that returns only the annotated JPEG."""
    if not current_app.model:
        return jsonify({'error': 'YOLO 模型未加载，无法检测。'}), 500
    try:
        frame = _decode_upload()
    except Exception as exc:
        return jsonify({'error': f'图片解析失败：{exc}'}), 400

    try:
        detected_frame, _ = render_detections(
            current_app.model,
            frame,
            current_app.config['CONF_THRESH'],
        )
        encoded, jpg_bytes = cv2.imencode('.jpg', detected_frame)
        if not encoded:
            raise ValueError('JPEG 编码失败')
    except Exception as exc:
        return jsonify({'error': f'YOLO 检测失败：{exc}'}), 500
    return Response(jpg_bytes.tobytes(), mimetype='image/jpeg')


@image_bp.route('/detect_image_report', methods=['POST'])
def detect_image_report():
    """Run YOLO, ask Kimi to review the result, and return a report."""
    if not current_app.model:
        return jsonify({'error': 'YOLO 模型未加载，无法检测。'}), 500
    try:
        frame = _decode_upload()
    except Exception as exc:
        return jsonify({'error': f'图片解析失败：{exc}'}), 400

    try:
        annotated_frame, detections = run_detections(
            current_app.model,
            frame,
            current_app.config['CONF_THRESH'],
        )
        original_ok, original_jpg = cv2.imencode('.jpg', frame)
        annotated_ok, annotated_jpg = cv2.imencode('.jpg', annotated_frame)
        if not original_ok or not annotated_ok:
            raise ValueError('JPEG 编码失败')
    except Exception as exc:
        return jsonify({'error': f'YOLO 检测失败：{exc}'}), 500

    if current_app.config['KIMI_REVIEW_ENABLED']:
        try:
            ai_review = current_app.ai_reviewer.review(
                original_jpg.tobytes(),
                annotated_jpg.tobytes(),
                detections,
            )
        except Exception as exc:
            current_app.logger.exception('Kimi vision review failed')
            ai_review = {
                'status': 'failed',
                'message': f'Kimi 复核失败：{type(exc).__name__}',
            }
    else:
        ai_review = {
            'status': 'disabled',
            'message': 'Kimi 视觉复核已通过配置关闭。',
        }

    report = build_detection_report(detections, ai_review)
    return jsonify({
        'success': True,
        'annotated_image': (
            'data:image/jpeg;base64,'
            + base64.b64encode(annotated_jpg.tobytes()).decode('ascii')
        ),
        'report': report,
    })
