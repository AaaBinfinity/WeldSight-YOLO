"""Safe data export, storage inspection, and cleanup operations."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _folder_stats(root):
    root = Path(root)
    files = 0
    directories = 0
    total_bytes = 0
    if not root.exists():
        return {
            'files': 0,
            'directories': 0,
            'bytes': 0,
        }
    for path in root.rglob('*'):
        try:
            if path.is_symlink():
                continue
            if path.is_dir():
                directories += 1
            elif path.is_file():
                files += 1
                total_bytes += path.stat().st_size
        except OSError:
            continue
    return {
        'files': files,
        'directories': directories,
        'bytes': total_bytes,
    }


class DataManagementService:
    """Manage only paths and database rows owned by WeldSight."""

    def __init__(self, app, store):
        self.app = app
        self.store = store
        self.data_folder = Path(app.config['DATA_FOLDER'])
        self.record_folder = Path(app.config['RECORD_FOLDER'])
        self.batch_folder = Path(app.config['BATCH_FOLDER'])
        self.upload_folder = Path(app.config['UPLOAD_FOLDER'])
        for root in (
            self.data_folder,
            self.record_folder,
            self.batch_folder,
            self.upload_folder,
        ):
            root.mkdir(parents=True, exist_ok=True)

    def overview(self):
        database = self.store.data_overview()
        records = _folder_stats(self.record_folder)
        batches = _folder_stats(self.batch_folder)
        uploads = _folder_stats(self.upload_folder)
        feedback_path = self.store.feedback_path
        feedback_bytes = (
            feedback_path.stat().st_size
            if feedback_path.exists()
            else 0
        )
        feedback_entries = 0
        if feedback_path.exists():
            with feedback_path.open(
                'r',
                encoding='utf-8',
                errors='ignore',
            ) as stream:
                feedback_entries = sum(1 for line in stream if line.strip())
        storage_bytes = (
            records['bytes']
            + batches['bytes']
            + uploads['bytes']
            + feedback_bytes
        )
        storage_files = (
            records['files']
            + batches['files']
            + uploads['files']
            + (1 if feedback_path.exists() else 0)
        )
        config = self.store.database_config
        return {
            'database': {
                **database,
                'engine': 'MySQL',
                'host': config.get('host', 'localhost'),
                'port': int(config.get('port', 3306)),
                'name': config.get('database', 'WeldSight'),
                'connected': True,
            },
            'storage': {
                'total_bytes': storage_bytes,
                'total_files': storage_files,
                'records': records,
                'batches': batches,
                'uploads': uploads,
                'feedback_entries': feedback_entries,
                'feedback_bytes': feedback_bytes,
            },
            'active_jobs': self.active_jobs(),
            'generated_at': _utc_now(),
        }

    def active_jobs(self):
        inspection_service = getattr(
            self.app,
            'inspection_service',
            None,
        )
        if not inspection_service:
            return {'ai_reviews': 0, 'batches': 0}
        return {
            'ai_reviews': len(
                getattr(inspection_service, '_active_ai', set())
            ),
            'batches': len(
                getattr(inspection_service, '_active_batches', set())
            ),
        }

    def export_payload(self, record_ids=None):
        records = self.store.export_inspections(record_ids)
        return {
            'schema': 'weldsight-data-export/v1',
            'exported_at': _utc_now(),
            'record_count': len(records),
            'records': [
                self._public_record(record)
                for record in records
            ],
        }

    def build_json_export(self, record_ids=None):
        content = json.dumps(
            self.export_payload(record_ids),
            ensure_ascii=False,
            indent=2,
        ).encode('utf-8')
        output = io.BytesIO(content)
        output.seek(0)
        return output

    def build_zip_export(self, record_ids=None, include_files=True):
        records = self.store.export_inspections(record_ids)
        payload = {
            'schema': 'weldsight-data-archive/v1',
            'exported_at': _utc_now(),
            'record_count': len(records),
            'includes_files': bool(include_files),
            'records': [
                self._public_record(record)
                for record in records
            ],
        }
        output = io.BytesIO()
        with zipfile.ZipFile(
            output,
            mode='w',
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                'weldsight-export.json',
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ).encode('utf-8'),
            )
            if include_files:
                for record in records:
                    self._add_record_files(archive, record)
                if self.store.feedback_path.exists():
                    archive.write(
                        self.store.feedback_path,
                        'training/training_feedback.jsonl',
                    )
        output.seek(0)
        return output

    def delete_records(self, record_ids):
        active = self.active_jobs()
        active_ids = set()
        inspection_service = getattr(
            self.app,
            'inspection_service',
            None,
        )
        if inspection_service:
            active_ids.update(
                getattr(inspection_service, '_active_ai', set())
            )
        requested_ids = list(dict.fromkeys(record_ids or []))
        blocked = sorted(active_ids.intersection(requested_ids))
        if blocked:
            raise RuntimeError('所选记录仍在 AI 复核中，请稍后再删除。')
        removed_records = self.store.delete_inspections(requested_ids)
        reclaimed_bytes = 0
        for record in removed_records:
            record_dir = self._safe_child(
                self.record_folder,
                record['id'],
            )
            reclaimed_bytes += self._remove_path(record_dir)
        return {
            'deleted_records': len(removed_records),
            'requested_records': len(requested_ids),
            'reclaimed_bytes': reclaimed_bytes,
            'active_jobs': active,
        }

    def cleanup_orphans(self):
        active = self.active_jobs()
        if active['ai_reviews'] or active['batches']:
            raise RuntimeError('后台任务仍在运行，暂不能清理孤立文件。')
        record_ids = self.store.list_record_ids()
        batch_ids = self.store.list_batch_ids()
        removed = []
        reclaimed_bytes = 0
        for root, known_ids, kind in (
            (self.record_folder, record_ids, 'record'),
            (self.batch_folder, batch_ids, 'batch'),
        ):
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir():
                    continue
                if child.name in known_ids:
                    continue
                safe_child = self._safe_child(root, child.name)
                reclaimed_bytes += self._remove_path(safe_child)
                removed.append({
                    'type': kind,
                    'name': child.name,
                })
        return {
            'removed_directories': len(removed),
            'reclaimed_bytes': reclaimed_bytes,
            'items': removed,
        }

    def purge_detection_data(self):
        active = self.active_jobs()
        if active['ai_reviews'] or active['batches']:
            raise RuntimeError('后台任务仍在运行，暂不能清空检测数据。')
        deleted = self.store.purge_detection_data()
        reclaimed_bytes = 0
        for root in (
            self.record_folder,
            self.batch_folder,
            self.upload_folder,
        ):
            for child in root.iterdir():
                if child.is_symlink():
                    continue
                reclaimed_bytes += self._remove_path(
                    self._safe_child(root, child.name)
                )
        reclaimed_bytes += self._remove_path(
            self.store.feedback_path,
            allowed_root=self.data_folder,
        )
        return {
            'deleted_records': len(deleted['inspections']),
            'deleted_batches': len(deleted['batch_ids']),
            'reclaimed_bytes': reclaimed_bytes,
            'settings_preserved': True,
        }

    @staticmethod
    def _public_record(record):
        public = {
            key: value
            for key, value in record.items()
            if key not in {'original_path', 'annotated_path'}
        }
        public['files'] = {
            'original': (
                f"records/{record['id']}/original"
                f"{Path(record['original_path']).suffix.lower() or '.jpg'}"
            ),
            'annotated': (
                f"records/{record['id']}/annotated"
                f"{Path(record['annotated_path']).suffix.lower() or '.jpg'}"
            ),
        }
        return public

    @staticmethod
    def _add_record_files(archive, record):
        for variant in ('original', 'annotated'):
            path = Path(record[f'{variant}_path'])
            if not path.exists() or not path.is_file():
                continue
            suffix = path.suffix.lower() or '.jpg'
            archive.write(
                path,
                f"records/{record['id']}/{variant}{suffix}",
            )

    @staticmethod
    def _safe_child(root, name):
        root = Path(root).resolve()
        child = (root / str(name)).resolve()
        try:
            child.relative_to(root)
        except ValueError as exc:
            raise ValueError('目标路径超出 WeldSight 数据目录。') from exc
        if child == root:
            raise ValueError('拒绝操作数据目录根路径。')
        return child

    @staticmethod
    def _remove_path(path, allowed_root=None):
        path = Path(path)
        if allowed_root is not None:
            allowed_root = Path(allowed_root).resolve()
            resolved = path.resolve()
            try:
                resolved.relative_to(allowed_root)
            except ValueError as exc:
                raise ValueError('目标路径超出 WeldSight 数据目录。') from exc
            if resolved == allowed_root:
                raise ValueError('拒绝操作数据目录根路径。')
        if not path.exists():
            return 0
        size = _folder_stats(path)['bytes'] if path.is_dir() else path.stat().st_size
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return size
