"""SQLite persistence for inspections, batches, reviews, alerts, and settings."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back and always release the Windows file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _json_load(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class InspectionStore:
    """Small thread-safe repository using one SQLite connection per operation."""

    def __init__(self, database_path, data_folder):
        self.database_path = Path(database_path)
        self.data_folder = Path(data_folder)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_folder.mkdir(parents=True, exist_ok=True)
        self.feedback_path = self.data_folder / 'training_feedback.jsonl'
        self._feedback_lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            check_same_thread=False,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA journal_mode = WAL')
        return connection

    def _initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS inspections (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_name TEXT NOT NULL,
            batch_id TEXT,
            status TEXT NOT NULL,
            ai_status TEXT NOT NULL,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            confidence_threshold REAL NOT NULL,
            original_path TEXT NOT NULL,
            annotated_path TEXT NOT NULL,
            image_width INTEGER NOT NULL,
            image_height INTEGER NOT NULL,
            detection_count INTEGER NOT NULL,
            class_counts TEXT NOT NULL,
            detections TEXT NOT NULL,
            ai_review TEXT NOT NULL,
            conclusion TEXT NOT NULL,
            disclaimer TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            reviewer TEXT NOT NULL DEFAULT '',
            review_decision TEXT NOT NULL DEFAULT '',
            review_notes TEXT NOT NULL DEFAULT '',
            corrections TEXT NOT NULL DEFAULT '[]',
            reviewed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_inspections_created
            ON inspections(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_inspections_source
            ON inspections(source_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_inspections_status
            ON inspections(status, ai_status);
        CREATE INDEX IF NOT EXISTS idx_inspections_batch
            ON inspections(batch_id);

        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            record_ids TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
        with self._connect() as connection:
            connection.executescript(schema)

    def create_inspection(self, record):
        now = record.get('created_at') or utc_now()
        values = {
            'id': record.get('id') or uuid4().hex,
            'created_at': now,
            'updated_at': now,
            'source_type': record.get('source_type', 'image'),
            'source_name': record.get('source_name', 'unknown'),
            'batch_id': record.get('batch_id'),
            'status': record.get('status', 'completed'),
            'ai_status': record.get('ai_status', 'disabled'),
            'model_name': record.get('model_name', 'YOLO'),
            'model_version': record.get('model_version', ''),
            'confidence_threshold': float(record.get('confidence_threshold', 0.25)),
            'original_path': str(record.get('original_path', '')),
            'annotated_path': str(record.get('annotated_path', '')),
            'image_width': int(record.get('image_width', 0)),
            'image_height': int(record.get('image_height', 0)),
            'detection_count': int(record.get('detection_count', 0)),
            'class_counts': _json_dump(record.get('class_counts', {})),
            'detections': _json_dump(record.get('detections', [])),
            'ai_review': _json_dump(record.get('ai_review', {})),
            'conclusion': record.get('conclusion', ''),
            'disclaimer': record.get('disclaimer', ''),
            'project_name': record.get('project_name', ''),
            'reviewer': record.get('reviewer', ''),
        }
        columns = ', '.join(values)
        placeholders = ', '.join(f':{key}' for key in values)
        with self._connect() as connection:
            connection.execute(
                f'INSERT INTO inspections ({columns}) VALUES ({placeholders})',
                values,
            )
        return self.get_inspection(values['id'])

    def update_inspection(self, record_id, **changes):
        json_fields = {'class_counts', 'detections', 'ai_review', 'corrections'}
        allowed = {
            'status', 'ai_status', 'class_counts', 'detections', 'ai_review',
            'conclusion', 'disclaimer', 'reviewer', 'review_decision',
            'review_notes', 'corrections', 'reviewed_at', 'project_name',
            'detection_count', 'confidence_threshold',
        }
        values = {'id': record_id, 'updated_at': utc_now()}
        assignments = ['updated_at = :updated_at']
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key in json_fields:
                value = _json_dump(value)
            values[key] = value
            assignments.append(f'{key} = :{key}')
        if len(assignments) == 1:
            return self.get_inspection(record_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE inspections SET {', '.join(assignments)} WHERE id = :id",
                values,
            )
        return self.get_inspection(record_id)

    def get_inspection(self, record_id):
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM inspections WHERE id = ?',
                (record_id,),
            ).fetchone()
        return self._inspection_dict(row) if row else None

    def list_inspections(
        self,
        query='',
        source_type='',
        status='',
        ai_status='',
        review_decision='',
        batch_id='',
        limit=50,
        offset=0,
    ):
        clauses = []
        values = []
        if query:
            clauses.append(
                '(source_name LIKE ? OR project_name LIKE ? '
                'OR class_counts LIKE ? OR id LIKE ?)'
            )
            pattern = f'%{query}%'
            values.extend([pattern, pattern, pattern, pattern])
        for column, value in (
            ('source_type', source_type),
            ('status', status),
            ('ai_status', ai_status),
            ('review_decision', review_decision),
            ('batch_id', batch_id),
        ):
            if value:
                clauses.append(f'{column} = ?')
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self._connect() as connection:
            total = connection.execute(
                f'SELECT COUNT(*) FROM inspections {where}',
                values,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT * FROM inspections
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        return {
            'items': [self._inspection_dict(row) for row in rows],
            'total': total,
            'limit': limit,
            'offset': offset,
        }

    def save_human_review(
        self,
        record_id,
        decision,
        reviewer,
        notes,
        corrections,
        missed_defects,
    ):
        payload = {
            'corrections': corrections or [],
            'missed_defects': missed_defects or [],
        }
        record = self.update_inspection(
            record_id,
            status='reviewed',
            review_decision=decision,
            reviewer=reviewer,
            review_notes=notes,
            corrections=payload,
            reviewed_at=utc_now(),
        )
        if record:
            training_row = {
                'inspection_id': record['id'],
                'created_at': record['created_at'],
                'reviewed_at': record['reviewed_at'],
                'source_name': record['source_name'],
                'original_path': record['original_path'],
                'annotated_path': record['annotated_path'],
                'model_detections': record['detections'],
                'human_decision': decision,
                'reviewer': reviewer,
                'notes': notes,
                **payload,
            }
            with self._feedback_lock:
                with self.feedback_path.open('a', encoding='utf-8') as stream:
                    stream.write(_json_dump(training_row) + '\n')
        return record

    def create_batch(self, name, total):
        batch_id = uuid4().hex
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batches
                (id, created_at, updated_at, name, status, total)
                VALUES (?, ?, ?, ?, 'queued', ?)
                """,
                (batch_id, now, now, name, int(total)),
            )
        return self.get_batch(batch_id)

    def update_batch(self, batch_id, **changes):
        allowed = {
            'status', 'processed', 'completed', 'failed', 'record_ids', 'error'
        }
        values = {'id': batch_id, 'updated_at': utc_now()}
        assignments = ['updated_at = :updated_at']
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == 'record_ids':
                value = _json_dump(value)
            values[key] = value
            assignments.append(f'{key} = :{key}')
        with self._connect() as connection:
            connection.execute(
                f"UPDATE batches SET {', '.join(assignments)} WHERE id = :id",
                values,
            )
        return self.get_batch(batch_id)

    def get_batch(self, batch_id):
        with self._connect() as connection:
            row = connection.execute(
                'SELECT * FROM batches WHERE id = ?',
                (batch_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item['record_ids'] = _json_load(item['record_ids'], [])
        item['progress'] = (
            round(item['processed'] / item['total'] * 100, 1)
            if item['total'] else 0
        )
        return item

    def list_batches(self, limit=30):
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT * FROM batches ORDER BY created_at DESC LIMIT ?',
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [self.get_batch(row['id']) for row in rows]

    def get_settings(self, defaults=None):
        result = dict(defaults or {})
        with self._connect() as connection:
            rows = connection.execute('SELECT key, value FROM settings').fetchall()
        for row in rows:
            result[row['key']] = _json_load(row['value'], row['value'])
        return result

    def update_settings(self, settings):
        now = utc_now()
        with self._connect() as connection:
            for key, value in settings.items():
                connection.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, _json_dump(value), now),
                )
        return self.get_settings()

    def analytics(self, days=30):
        days = max(1, min(int(days), 365))
        start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT created_at, source_type, detection_count, detections,
                       class_counts, status, review_decision
                FROM inspections
                WHERE created_at >= ?
                ORDER BY created_at ASC
                """,
                (f'{start.isoformat()}T00:00:00',),
            ).fetchall()

        class_counts = Counter()
        source_counts = Counter()
        review_counts = Counter()
        confidence_values = []
        daily = defaultdict(lambda: {'inspections': 0, 'defects': 0})
        defect_records = 0
        for row in rows:
            created_day = row['created_at'][:10]
            count = int(row['detection_count'])
            daily[created_day]['inspections'] += 1
            daily[created_day]['defects'] += count
            if count:
                defect_records += 1
            class_counts.update(_json_load(row['class_counts'], {}))
            source_counts[row['source_type']] += 1
            review_counts[row['review_decision'] or 'pending'] += 1
            for detection in _json_load(row['detections'], []):
                confidence = detection.get('confidence')
                if isinstance(confidence, (int, float)):
                    confidence_values.append(float(confidence))

        trend = []
        for index in range(days):
            date_value = start + timedelta(days=index)
            key = date_value.isoformat()
            trend.append({'date': key, **daily[key]})
        total = len(rows)
        return {
            'window_days': days,
            'total_inspections': total,
            'defect_records': defect_records,
            'defect_rate': round(defect_records / total * 100, 1) if total else 0,
            'total_detections': sum(class_counts.values()),
            'average_confidence': (
                round(sum(confidence_values) / len(confidence_values), 4)
                if confidence_values else 0
            ),
            'class_distribution': [
                {'name': name, 'value': value}
                for name, value in class_counts.most_common()
            ],
            'source_distribution': [
                {'name': name, 'value': value}
                for name, value in source_counts.most_common()
            ],
            'review_distribution': [
                {'name': name, 'value': value}
                for name, value in review_counts.most_common()
            ],
            'daily_trend': trend,
            'generated_at': utc_now(),
        }

    @staticmethod
    def _inspection_dict(row):
        item = dict(row)
        item['class_counts'] = _json_load(item['class_counts'], {})
        item['detections'] = _json_load(item['detections'], [])
        item['ai_review'] = _json_load(item['ai_review'], {})
        item['corrections'] = _json_load(item['corrections'], [])
        return item
