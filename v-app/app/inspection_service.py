"""Inspection orchestration, storage, async AI review, and batch processing."""

from __future__ import annotations

import io
import threading
from collections import Counter
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from app.inference import run_detections
from app.inspection_store import utc_now
from app.reporting import build_detection_report


class InspectionService:
    def __init__(self, app, store):
        self.app = app
        self.store = store
        self.record_folder = Path(app.config['RECORD_FOLDER'])
        self.batch_folder = Path(app.config['BATCH_FOLDER'])
        self.record_folder.mkdir(parents=True, exist_ok=True)
        self.batch_folder.mkdir(parents=True, exist_ok=True)
        self._ai_lock = threading.Lock()
        self._active_ai = set()
        self._batch_lock = threading.Lock()
        self._active_batches = set()

    @staticmethod
    def decode_image(image_bytes):
        pil_image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    @staticmethod
    def encode_jpeg(frame, quality=92):
        encoded, jpeg = cv2.imencode(
            '.jpg',
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)],
        )
        if not encoded:
            raise ValueError('JPEG 编码失败')
        return jpeg.tobytes()

    def process_upload(
        self,
        image_bytes,
        source_name,
        source_type='image',
        batch_id=None,
        confidence_threshold=None,
        project_name='',
        reviewer='',
        queue_ai=True,
    ):
        if not self.app.model:
            raise RuntimeError('YOLO 模型未加载，无法检测。')
        frame = self.decode_image(image_bytes)
        threshold = self._safe_threshold(confidence_threshold)
        annotated_frame, detections = run_detections(
            self.app.model,
            frame,
            threshold,
        )
        original_jpeg = self.encode_jpeg(frame)
        annotated_jpeg = self.encode_jpeg(annotated_frame)
        return self.save_result(
            original_jpeg=original_jpeg,
            annotated_jpeg=annotated_jpeg,
            detections=detections,
            source_name=source_name,
            source_type=source_type,
            batch_id=batch_id,
            confidence_threshold=threshold,
            image_width=frame.shape[1],
            image_height=frame.shape[0],
            project_name=project_name,
            reviewer=reviewer,
            queue_ai=queue_ai,
        )

    def save_result(
        self,
        original_jpeg,
        annotated_jpeg,
        detections,
        source_name,
        source_type='image',
        batch_id=None,
        confidence_threshold=None,
        image_width=0,
        image_height=0,
        project_name='',
        reviewer='',
        queue_ai=True,
    ):
        record_id = uuid4().hex
        record_dir = self.record_folder / record_id
        record_dir.mkdir(parents=True, exist_ok=True)
        original_path = record_dir / 'original.jpg'
        annotated_path = record_dir / 'annotated.jpg'
        original_path.write_bytes(original_jpeg)
        annotated_path.write_bytes(annotated_jpeg)

        ai_enabled = (
            queue_ai
            and self.app.config.get('KIMI_REVIEW_ENABLED', True)
            and self.app.ai_reviewer.available
        )
        if ai_enabled:
            ai_review = {
                'status': 'queued',
                'message': 'YOLO 检测已完成，Kimi 复核正在后台排队。',
            }
            status = 'ai_pending'
        elif self.app.config.get('KIMI_REVIEW_ENABLED', True):
            ai_review = {
                'status': 'not_configured',
                'message': '未配置 MOONSHOT_API_KEY，已保留 YOLO 检测结果。',
            }
            status = 'completed'
        else:
            ai_review = {
                'status': 'disabled',
                'message': 'Kimi 视觉复核已通过设置关闭。',
            }
            status = 'completed'

        report = build_detection_report(
            detections,
            ai_review,
            report_id=record_id,
        )
        counts = Counter(item['class_name'] for item in detections)
        record = self.store.create_inspection({
            'id': record_id,
            'created_at': report['generated_at'],
            'source_type': source_type,
            'source_name': source_name,
            'batch_id': batch_id,
            'status': status,
            'ai_status': ai_review['status'],
            'model_name': Path(self.app.config['MODEL_PATH']).name,
            'model_version': self.app.config.get('YOLO_MODEL_VERSION', 'YOLOv11'),
            'confidence_threshold': (
                confidence_threshold
                if confidence_threshold is not None
                else self.app.config['CONF_THRESH']
            ),
            'original_path': str(original_path),
            'annotated_path': str(annotated_path),
            'image_width': image_width,
            'image_height': image_height,
            'detection_count': len(detections),
            'class_counts': dict(sorted(counts.items())),
            'detections': detections,
            'ai_review': ai_review,
            'conclusion': report['conclusion'],
            'disclaimer': report['disclaimer'],
            'project_name': project_name,
            'reviewer': reviewer,
        })
        if ai_enabled:
            self.queue_ai_review(record_id)
        return record

    def queue_ai_review(self, record_id):
        record = self.store.get_inspection(record_id)
        if not record:
            raise KeyError(record_id)
        if not self.app.ai_reviewer.available:
            return self.store.update_inspection(
                record_id,
                status='completed',
                ai_status='not_configured',
                ai_review={
                    'status': 'not_configured',
                    'message': '未配置 MOONSHOT_API_KEY，无法进行 AI 复核。',
                },
            )
        with self._ai_lock:
            if record_id in self._active_ai:
                return record
            self._active_ai.add(record_id)
        self.store.update_inspection(
            record_id,
            status='ai_pending',
            ai_status='queued',
            ai_review={
                'status': 'queued',
                'message': 'AI 复核任务已加入后台队列。',
            },
        )
        thread = threading.Thread(
            target=self._run_ai_review,
            args=(record_id,),
            daemon=True,
            name=f'ai-review-{record_id[:8]}',
        )
        thread.start()
        return self.store.get_inspection(record_id)

    def _run_ai_review(self, record_id):
        try:
            self.store.update_inspection(
                record_id,
                ai_status='processing',
                ai_review={
                    'status': 'processing',
                    'message': 'Kimi Vision 正在复核原图与检测结果。',
                },
            )
            record = self.store.get_inspection(record_id)
            review = self.app.ai_reviewer.review(
                Path(record['original_path']).read_bytes(),
                Path(record['annotated_path']).read_bytes(),
                record['detections'],
            )
            report = build_detection_report(
                record['detections'],
                review,
                report_id=record_id,
                generated_at=record['created_at'],
            )
            current_record = self.store.get_inspection(record_id) or record
            self.store.update_inspection(
                record_id,
                status=(
                    'reviewed'
                    if current_record.get('review_decision')
                    else 'completed'
                ),
                ai_status=review.get('status', 'completed'),
                ai_review=review,
                conclusion=report['conclusion'],
                disclaimer=report['disclaimer'],
            )
        except Exception as exc:
            self.app.logger.exception(
                'Background Kimi review failed for %s',
                record_id,
            )
            current_record = self.store.get_inspection(record_id) or {}
            self.store.update_inspection(
                record_id,
                status=(
                    'reviewed'
                    if current_record.get('review_decision')
                    else 'ai_failed'
                ),
                ai_status='failed',
                ai_review={
                    'status': 'failed',
                    'message': (
                        f'Kimi 复核暂时失败：{type(exc).__name__}。'
                        'YOLO 结果已保存，可稍后重新复核。'
                    ),
                    'retryable': True,
                },
            )
        finally:
            with self._ai_lock:
                self._active_ai.discard(record_id)

    def start_batch(self, batch_id, inputs, options):
        with self._batch_lock:
            if batch_id in self._active_batches:
                return
            self._active_batches.add(batch_id)
        thread = threading.Thread(
            target=self._run_batch,
            args=(batch_id, inputs, options),
            daemon=True,
            name=f'batch-{batch_id[:8]}',
        )
        thread.start()

    def _run_batch(self, batch_id, inputs, options):
        processed = completed = failed = 0
        record_ids = []
        self.store.update_batch(batch_id, status='processing')
        try:
            for item in inputs:
                try:
                    record = self.process_upload(
                        image_bytes=Path(item['path']).read_bytes(),
                        source_name=item['name'],
                        source_type='batch',
                        batch_id=batch_id,
                        confidence_threshold=options.get('confidence_threshold'),
                        project_name=options.get('project_name', ''),
                        reviewer=options.get('reviewer', ''),
                        queue_ai=True,
                    )
                    record_ids.append(record['id'])
                    completed += 1
                except Exception as exc:
                    failed += 1
                    self.app.logger.exception(
                        'Batch %s failed on %s',
                        batch_id,
                        item['name'],
                    )
                processed += 1
                self.store.update_batch(
                    batch_id,
                    processed=processed,
                    completed=completed,
                    failed=failed,
                    record_ids=record_ids,
                )
            self.store.update_batch(
                batch_id,
                status='completed' if not failed else 'completed_with_errors',
                processed=processed,
                completed=completed,
                failed=failed,
                record_ids=record_ids,
            )
        except Exception as exc:
            self.app.logger.exception('Batch %s aborted', batch_id)
            self.store.update_batch(
                batch_id,
                status='failed',
                error=str(exc),
                processed=processed,
                completed=completed,
                failed=failed,
                record_ids=record_ids,
            )
        finally:
            with self._batch_lock:
                self._active_batches.discard(batch_id)

    def save_batch_inputs(self, batch_id, uploads):
        batch_dir = self.batch_folder / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for index, upload in enumerate(uploads):
            safe_name = Path(upload.filename or f'image-{index + 1}.jpg').name
            suffix = Path(safe_name).suffix.lower() or '.jpg'
            path = batch_dir / f'{index:04d}{suffix}'
            path.write_bytes(upload.read())
            saved.append({'name': safe_name, 'path': str(path)})
        return saved

    def record_to_api(self, record):
        if not record:
            return None
        report = {
            'report_id': record['id'],
            'generated_at': record['created_at'],
            'yolo': {
                'detection_count': record['detection_count'],
                'class_counts': record['class_counts'],
                'detections': record['detections'],
            },
            'ai_review': record['ai_review'],
            'conclusion': record['conclusion'],
            'disclaimer': record['disclaimer'],
        }
        item = {
            key: value
            for key, value in record.items()
            if key not in {'original_path', 'annotated_path'}
        }
        item.update({
            'original_image_url': f"/api/inspections/{record['id']}/original",
            'annotated_image_url': f"/api/inspections/{record['id']}/annotated",
            'pdf_url': f"/api/inspections/{record['id']}/pdf",
            'report': report,
        })
        return item

    def _safe_threshold(self, value):
        if value is None or value == '':
            return float(self.app.config['CONF_THRESH'])
        return max(0.05, min(float(value), 0.95))
