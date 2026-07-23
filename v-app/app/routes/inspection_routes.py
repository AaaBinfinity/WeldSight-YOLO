"""Persistent inspection, batch, review, analytics, settings, and PDF APIs."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, jsonify, request, send_file

from app.pdf_reports import build_batch_pdf, build_inspection_pdf
from app.routes import inspection_bp


ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
HUMAN_DECISIONS = {'confirmed', 'false_positive', 'missed_defect', 'mixed', 'accepted'}


def _service():
    return current_app.inspection_service


def _store():
    return current_app.inspection_store


def _record_or_404(record_id):
    record = _store().get_inspection(record_id)
    if not record:
        return None, (jsonify({'error': '未找到检测记录。'}), 404)
    return record, None


def _public_settings():
    settings = _store().get_settings(current_app.settings_defaults)
    return {
        **settings,
        'api_key_configured': bool(current_app.config.get('MOONSHOT_API_KEY')),
        'model_loaded': bool(current_app.model),
        'model_path': Path(current_app.config['MODEL_PATH']).name,
    }


@inspection_bp.route('/api/inspections', methods=['POST'])
def create_inspection():
    upload = request.files.get('image')
    if not upload or not upload.filename:
        return jsonify({'error': "请通过 'image' 字段上传图片。"}), 400
    if Path(upload.filename).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': '仅支持 PNG、JPEG 和 WebP 图片。'}), 400
    try:
        record = _service().process_upload(
            image_bytes=upload.read(),
            source_name=Path(upload.filename).name,
            source_type='image',
            confidence_threshold=request.form.get('confidence_threshold'),
            project_name=request.form.get('project_name', ''),
            reviewer=request.form.get('reviewer', ''),
            queue_ai=True,
        )
    except ValueError as exc:
        return jsonify({'error': f'图片解析失败：{exc}'}), 400
    except Exception as exc:
        current_app.logger.exception('Inspection creation failed')
        return jsonify({'error': f'检测失败：{exc}'}), 500
    return jsonify({
        'success': True,
        'inspection': _service().record_to_api(record),
    }), 201


@inspection_bp.route('/api/inspections', methods=['GET'])
def list_inspections():
    result = _store().list_inspections(
        query=request.args.get('q', '').strip(),
        source_type=request.args.get('source_type', '').strip(),
        status=request.args.get('status', '').strip(),
        ai_status=request.args.get('ai_status', '').strip(),
        review_decision=request.args.get('review_decision', '').strip(),
        batch_id=request.args.get('batch_id', '').strip(),
        limit=request.args.get('limit', 50),
        offset=request.args.get('offset', 0),
    )
    result['items'] = [
        _service().record_to_api(record)
        for record in result['items']
    ]
    return jsonify(result)


@inspection_bp.route('/api/inspections/<record_id>', methods=['GET'])
def get_inspection(record_id):
    record, error = _record_or_404(record_id)
    if error:
        return error
    return jsonify({'inspection': _service().record_to_api(record)})


def _send_inspection_image(record_id, variant):
    record, error = _record_or_404(record_id)
    if error:
        return error
    path = Path(record[f'{variant}_path'])
    if not path.exists():
        return jsonify({'error': '图像文件不存在。'}), 404
    return send_file(path, mimetype='image/jpeg', conditional=True)


@inspection_bp.route('/api/inspections/<record_id>/original', methods=['GET'])
def get_inspection_original(record_id):
    return _send_inspection_image(record_id, 'original')


@inspection_bp.route('/api/inspections/<record_id>/annotated', methods=['GET'])
def get_inspection_annotated(record_id):
    return _send_inspection_image(record_id, 'annotated')


@inspection_bp.route('/api/inspections/<record_id>/re-review', methods=['POST'])
def retry_ai_review(record_id):
    record, error = _record_or_404(record_id)
    if error:
        return error
    try:
        queued = _service().queue_ai_review(record['id'])
    except Exception as exc:
        return jsonify({'error': f'无法重新复核：{exc}'}), 409
    return jsonify({
        'success': True,
        'inspection': _service().record_to_api(queued),
    })


@inspection_bp.route('/api/inspections/<record_id>/human-review', methods=['POST'])
def save_human_review(record_id):
    record, error = _record_or_404(record_id)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    decision = str(payload.get('decision', '')).strip()
    if decision not in HUMAN_DECISIONS:
        return jsonify({'error': '请选择有效的人工复核结论。'}), 400
    reviewer = str(payload.get('reviewer', '')).strip()[:80]
    notes = str(payload.get('notes', '')).strip()[:2000]
    corrections = payload.get('corrections') or []
    missed_defects = payload.get('missed_defects') or []
    if not isinstance(corrections, list) or not isinstance(missed_defects, list):
        return jsonify({'error': '复核修正数据格式错误。'}), 400
    reviewed = _store().save_human_review(
        record_id=record['id'],
        decision=decision,
        reviewer=reviewer,
        notes=notes,
        corrections=corrections,
        missed_defects=missed_defects,
    )
    return jsonify({
        'success': True,
        'inspection': _service().record_to_api(reviewed),
        'training_feedback_saved': True,
    })


@inspection_bp.route('/api/inspections/<record_id>/pdf', methods=['GET'])
def inspection_pdf(record_id):
    record, error = _record_or_404(record_id)
    if error:
        return error
    pdf = build_inspection_pdf(record, _public_settings())
    return send_file(
        pdf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'weldsight-{record_id[:12]}.pdf',
    )


@inspection_bp.route('/api/batches', methods=['POST'])
def create_batch():
    uploads = [
        upload
        for upload in request.files.getlist('images')
        if upload and upload.filename
    ]
    max_images = int(current_app.config.get('BATCH_MAX_IMAGES', 50))
    if not uploads:
        return jsonify({'error': "请通过 'images' 字段上传多张图片。"}), 400
    if len(uploads) > max_images:
        return jsonify({'error': f'单个批次最多支持 {max_images} 张图片。'}), 400
    invalid = [
        upload.filename
        for upload in uploads
        if Path(upload.filename).suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS
    ]
    if invalid:
        return jsonify({'error': f"存在不支持的文件：{', '.join(invalid[:3])}"}), 400

    batch = _store().create_batch(
        request.form.get('name', '').strip() or '未命名检测批次',
        len(uploads),
    )
    saved = _service().save_batch_inputs(batch['id'], uploads)
    _service().start_batch(
        batch['id'],
        saved,
        {
            'confidence_threshold': request.form.get('confidence_threshold'),
            'project_name': request.form.get('project_name', ''),
            'reviewer': request.form.get('reviewer', ''),
        },
    )
    return jsonify({'success': True, 'batch': _store().get_batch(batch['id'])}), 202


@inspection_bp.route('/api/batches', methods=['GET'])
def list_batches():
    return jsonify({'items': _store().list_batches(request.args.get('limit', 30))})


@inspection_bp.route('/api/batches/<batch_id>', methods=['GET'])
def get_batch(batch_id):
    batch = _store().get_batch(batch_id)
    if not batch:
        return jsonify({'error': '未找到检测批次。'}), 404
    records = _store().list_inspections(batch_id=batch_id, limit=200)['items']
    return jsonify({
        'batch': batch,
        'records': [_service().record_to_api(record) for record in records],
    })


@inspection_bp.route('/api/batches/<batch_id>/pdf', methods=['GET'])
def batch_pdf(batch_id):
    batch = _store().get_batch(batch_id)
    if not batch:
        return jsonify({'error': '未找到检测批次。'}), 404
    records = _store().list_inspections(batch_id=batch_id, limit=200)['items']
    pdf = build_batch_pdf(batch, records, _public_settings())
    return send_file(
        pdf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'weldsight-batch-{batch_id[:12]}.pdf',
    )


@inspection_bp.route('/api/analytics/summary', methods=['GET'])
def analytics_summary():
    days = request.args.get('days', 30)
    analytics = _store().analytics(days)
    recent = _store().list_inspections(limit=8)['items']
    analytics['recent_inspections'] = [
        _service().record_to_api(record) for record in recent
    ]
    return jsonify(analytics)


@inspection_bp.route('/api/alerts', methods=['GET'])
def list_alerts():
    result = _store().list_inspections(
        source_type='camera',
        limit=request.args.get('limit', 20),
    )
    result['items'] = [
        _service().record_to_api(record) for record in result['items']
    ]
    return jsonify(result)


@inspection_bp.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(_public_settings())


@inspection_bp.route('/api/settings', methods=['PUT'])
def update_settings():
    payload = request.get_json(silent=True) or {}

    def parse_boolean(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {'true', '1', 'yes', 'on'}:
                return True
            if normalized in {'false', '0', 'no', 'off'}:
                return False
        raise ValueError('invalid boolean')

    validators = {
        'project_name': lambda value: str(value).strip()[:100],
        'organization': lambda value: str(value).strip()[:120],
        'default_reviewer': lambda value: str(value).strip()[:80],
        'conf_thresh': lambda value: max(0.05, min(float(value), 0.95)),
        'kimi_review_enabled': parse_boolean,
        'kimi_model': lambda value: str(value).strip()[:80],
        'kimi_fallback_models': lambda value: [
            str(item).strip()[:80]
            for item in (value if isinstance(value, list) else str(value).split(','))
            if str(item).strip()
        ][:6],
        'kimi_max_retries': lambda value: max(1, min(int(value), 8)),
        'camera_default_index': lambda value: max(0, int(value)),
        'alert_cooldown_seconds': lambda value: max(1, min(int(value), 600)),
    }
    cleaned = {}
    try:
        for key, validator in validators.items():
            if key in payload:
                cleaned[key] = validator(payload[key])
    except (TypeError, ValueError):
        return jsonify({'error': '设置值格式错误。'}), 400
    if not cleaned:
        return jsonify({'error': '没有可更新的设置。'}), 400
    _store().update_settings(cleaned)
    current_app.apply_runtime_settings()
    return jsonify({'success': True, 'settings': _public_settings()})
