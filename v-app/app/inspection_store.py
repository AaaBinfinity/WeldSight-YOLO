"""MySQL persistence for inspections, batches, reviews, and settings."""

from __future__ import annotations

import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.defect_classes import (
    canonicalize_ai_review,
    canonicalize_class_counts,
    canonicalize_detections,
    canonicalize_record,
)

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    pymysql = None
    DictCursor = None


def _mysql_sql(sql):
    sql = re.sub(r':([A-Za-z_][A-Za-z0-9_]*)', r'%(\1)s', sql)
    return sql.replace('?', '%s')


class MySQLConnection:
    """Expose the connection API used by InspectionStore."""

    def __init__(self, config):
        if pymysql is None:
            raise RuntimeError(
                '缺少 PyMySQL 依赖，请先执行 uv sync 安装项目依赖。'
            )
        self.connection = pymysql.connect(
            host=config['host'],
            port=int(config['port']),
            user=config['user'],
            password=config['password'],
            database=config['database'],
            charset='utf8mb4',
            connect_timeout=int(config.get('connect_timeout', 10)),
            cursorclass=DictCursor,
            autocommit=False,
        )

    def execute(self, sql, parameters=None):
        cursor = self.connection.cursor()
        cursor.execute(_mysql_sql(sql), parameters)
        return cursor

    def executescript(self, script):
        cursor = self.connection.cursor()
        for statement in script.split(';'):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
        return cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
        return False


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
    """Small thread-safe repository using one database connection per operation."""

    def __init__(self, database, data_folder):
        self.database_config = dict(database)
        self.data_folder = Path(data_folder)
        self.data_folder.mkdir(parents=True, exist_ok=True)
        self.feedback_path = self.data_folder / 'training_feedback.jsonl'
        self._feedback_lock = threading.Lock()
        self._initialize()

    def _connect(self):
        return MySQLConnection(self.database_config)

    def _initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS inspections (
            id VARCHAR(32) PRIMARY KEY,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_name VARCHAR(255) NOT NULL,
            batch_id VARCHAR(32) NULL,
            status VARCHAR(32) NOT NULL,
            ai_status VARCHAR(32) NOT NULL,
            model_name VARCHAR(255) NOT NULL,
            model_version VARCHAR(128) NOT NULL,
            confidence_threshold DOUBLE NOT NULL,
            original_path VARCHAR(1024) NOT NULL,
            annotated_path VARCHAR(1024) NOT NULL,
            image_width INT NOT NULL,
            image_height INT NOT NULL,
            detection_count INT NOT NULL,
            class_counts LONGTEXT NOT NULL,
            detections LONGTEXT NOT NULL,
            ai_review LONGTEXT NOT NULL,
            conclusion LONGTEXT NOT NULL,
            disclaimer LONGTEXT NOT NULL,
            project_name VARCHAR(255) NOT NULL DEFAULT '',
            reviewer VARCHAR(128) NOT NULL DEFAULT '',
            review_decision VARCHAR(32) NOT NULL DEFAULT '',
            review_notes LONGTEXT NOT NULL,
            corrections LONGTEXT NOT NULL,
            reviewed_at VARCHAR(40) NULL,
            KEY idx_inspections_created (created_at),
            KEY idx_inspections_source (source_type, created_at),
            KEY idx_inspections_status (status, ai_status),
            KEY idx_inspections_batch (batch_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COLLATE=utf8mb4_unicode_ci;

        CREATE TABLE IF NOT EXISTS batches (
            id VARCHAR(32) PRIMARY KEY,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL,
            total INT NOT NULL,
            processed INT NOT NULL DEFAULT 0,
            completed INT NOT NULL DEFAULT 0,
            failed INT NOT NULL DEFAULT 0,
            record_ids LONGTEXT NOT NULL,
            error LONGTEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COLLATE=utf8mb4_unicode_ci;

        CREATE TABLE IF NOT EXISTS settings (
            `key` VARCHAR(128) PRIMARY KEY,
            value LONGTEXT NOT NULL,
            updated_at VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
          COLLATE=utf8mb4_unicode_ci;
        """
        with self._connect() as connection:
            connection.executescript(schema)

    def create_inspection(self, record):
        record = canonicalize_record(record)
        now = record.get('created_at') or utc_now()
        values = {
            'id': record.get('id') or uuid4().hex,
            'created_at': now,
            'updated_at': record.get('updated_at') or now,
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
            'review_decision': record.get('review_decision', ''),
            'review_notes': record.get('review_notes', ''),
            'corrections': _json_dump(record.get('corrections', [])),
            'reviewed_at': record.get('reviewed_at'),
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
            if key == 'class_counts':
                value = canonicalize_class_counts(value)
            elif key == 'detections':
                value = canonicalize_detections(value)
            elif key == 'ai_review':
                value = canonicalize_ai_review(value)
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
            total_row = connection.execute(
                f'SELECT COUNT(*) AS total FROM inspections {where}',
                values,
            ).fetchone()
            total = (
                total_row['total']
                if isinstance(total_row, dict)
                else total_row[0]
            )
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
                (
                    id, created_at, updated_at, name, status, total,
                    processed, completed, failed, record_ids, error
                )
                VALUES (?, ?, ?, ?, 'queued', ?, 0, 0, 0, '[]', '')
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

    def data_overview(self):
        """Return database-level counts without exposing connection credentials."""
        with self._connect() as connection:
            inspection_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_records,
                    COALESCE(SUM(detection_count), 0) AS total_detections,
                    COALESCE(SUM(
                        CASE WHEN review_decision <> '' THEN 1 ELSE 0 END
                    ), 0) AS reviewed_records,
                    COALESCE(SUM(
                        CASE WHEN ai_status = 'completed' THEN 1 ELSE 0 END
                    ), 0) AS ai_completed,
                    COALESCE(SUM(
                        CASE
                            WHEN ai_status IN ('queued', 'processing')
                            THEN 1 ELSE 0
                        END
                    ), 0) AS ai_pending,
                    COALESCE(SUM(
                        CASE WHEN ai_status = 'failed' THEN 1 ELSE 0 END
                    ), 0) AS ai_failed,
                    MAX(updated_at) AS last_updated
                FROM inspections
                """
            ).fetchone()
            batch_row = connection.execute(
                'SELECT COUNT(*) AS total_batches FROM batches'
            ).fetchone()
            source_rows = connection.execute(
                """
                SELECT source_type, COUNT(*) AS count
                FROM inspections
                GROUP BY source_type
                ORDER BY count DESC
                """
            ).fetchall()
        overview = {
            key: (
                int(value)
                if key not in {'last_updated'} and value is not None
                else value
            )
            for key, value in dict(inspection_row).items()
        }
        overview['total_batches'] = int(batch_row['total_batches'])
        overview['source_counts'] = {
            row['source_type']: int(row['count'])
            for row in source_rows
        }
        return overview

    def list_record_ids(self):
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT id FROM inspections'
            ).fetchall()
        return {row['id'] for row in rows}

    def list_batch_ids(self):
        with self._connect() as connection:
            rows = connection.execute('SELECT id FROM batches').fetchall()
        return {row['id'] for row in rows}

    def export_inspections(self, record_ids=None):
        record_ids = list(dict.fromkeys(record_ids or []))
        with self._connect() as connection:
            if record_ids:
                placeholders = ', '.join('?' for _ in record_ids)
                rows = connection.execute(
                    f"""
                    SELECT * FROM inspections
                    WHERE id IN ({placeholders})
                    ORDER BY created_at DESC
                    """,
                    record_ids,
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM inspections
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        return [self._inspection_dict(row) for row in rows]

    def delete_inspections(self, record_ids):
        """Delete exact records and remove their IDs from batch metadata."""
        record_ids = list(dict.fromkeys(
            str(record_id).strip()
            for record_id in (record_ids or [])
            if str(record_id).strip()
        ))
        if not record_ids:
            return []
        placeholders = ', '.join('?' for _ in record_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f'SELECT * FROM inspections WHERE id IN ({placeholders})',
                record_ids,
            ).fetchall()
            found_ids = {row['id'] for row in rows}
            if not found_ids:
                return []
            found_placeholders = ', '.join('?' for _ in found_ids)
            connection.execute(
                f'DELETE FROM inspections WHERE id IN ({found_placeholders})',
                list(found_ids),
            )
            batches = connection.execute(
                'SELECT id, record_ids FROM batches'
            ).fetchall()
            for batch in batches:
                current_ids = _json_load(batch['record_ids'], [])
                remaining_ids = [
                    record_id
                    for record_id in current_ids
                    if record_id not in found_ids
                ]
                if remaining_ids != current_ids:
                    connection.execute(
                        """
                        UPDATE batches
                        SET record_ids = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            _json_dump(remaining_ids),
                            utc_now(),
                            batch['id'],
                        ),
                    )
        return [self._inspection_dict(row) for row in rows]

    def purge_detection_data(self):
        """Delete inspections and batches while intentionally preserving settings."""
        with self._connect() as connection:
            inspection_rows = connection.execute(
                'SELECT * FROM inspections'
            ).fetchall()
            batch_rows = connection.execute(
                'SELECT id FROM batches'
            ).fetchall()
            connection.execute('DELETE FROM inspections')
            connection.execute('DELETE FROM batches')
        return {
            'inspections': [
                self._inspection_dict(row)
                for row in inspection_rows
            ],
            'batch_ids': [row['id'] for row in batch_rows],
        }

    def get_settings(self, defaults=None):
        result = dict(defaults or {})
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT `key` AS setting_key, value FROM settings'
            ).fetchall()
        for row in rows:
            result[row['setting_key']] = _json_load(
                row['value'],
                row['value'],
            )
        return result

    def update_settings(self, settings):
        now = utc_now()
        with self._connect() as connection:
            for key, value in settings.items():
                connection.execute(
                    """
                    INSERT INTO settings (`key`, value, updated_at)
                    VALUES (?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        value = VALUES(value),
                        updated_at = VALUES(updated_at)
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
            class_counts.update(canonicalize_class_counts(
                _json_load(row['class_counts'], {})
            ))
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
        return canonicalize_record(item)
