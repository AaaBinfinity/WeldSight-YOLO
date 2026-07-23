import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / 'v-app'
load_dotenv(PROJECT_ROOT / '.env')
sys.path.insert(0, str(APP_ROOT))
APP_PACKAGE = ModuleType('app')
APP_PACKAGE.__path__ = [str(APP_ROOT / 'app')]
sys.modules.setdefault('app', APP_PACKAGE)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STORE_MODULE = load_module(
    'weldsight_data_store',
    APP_ROOT / 'app' / 'inspection_store.py',
)
DATA_MODULE = load_module(
    'weldsight_data_management',
    APP_ROOT / 'app' / 'data_management.py',
)
InspectionStore = STORE_MODULE.InspectionStore
DataManagementService = DATA_MODULE.DataManagementService

MYSQL_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'localhost'),
    'port': int(os.environ.get('MYSQL_PORT', '3306')),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'database': os.environ.get('MYSQL_DATABASE', 'WeldSight'),
    'connect_timeout': int(os.environ.get('MYSQL_CONNECT_TIMEOUT', '10')),
}


class DataManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / 'data'
        self.record_root = self.data_root / 'records'
        self.batch_root = self.data_root / 'batches'
        self.upload_root = self.root / 'uploads'
        self.store = InspectionStore(MYSQL_CONFIG, self.data_root)
        self.app = SimpleNamespace(
            config={
                'DATA_FOLDER': str(self.data_root),
                'RECORD_FOLDER': str(self.record_root),
                'BATCH_FOLDER': str(self.batch_root),
                'UPLOAD_FOLDER': str(self.upload_root),
            },
        )
        self.manager = DataManagementService(self.app, self.store)
        self.record_ids = []
        self.batch_ids = []

    def tearDown(self):
        try:
            with self.store._connect() as connection:
                for record_id in self.record_ids:
                    connection.execute(
                        'DELETE FROM inspections WHERE id = ?',
                        (record_id,),
                    )
                for batch_id in self.batch_ids:
                    connection.execute(
                        'DELETE FROM batches WHERE id = ?',
                        (batch_id,),
                    )
        finally:
            self.temporary.cleanup()

    def create_record(self, batch_id=None):
        record_id = uuid4().hex
        record_dir = self.record_root / record_id
        record_dir.mkdir(parents=True)
        original = record_dir / 'original.jpg'
        annotated = record_dir / 'annotated.jpg'
        original.write_bytes(b'original-image')
        annotated.write_bytes(b'annotated-image')
        record = self.store.create_inspection({
            'id': record_id,
            'source_type': 'batch' if batch_id else 'image',
            'source_name': f'data-management-{record_id[:8]}.jpg',
            'batch_id': batch_id,
            'status': 'completed',
            'ai_status': 'completed',
            'model_name': 'best_v8.pt',
            'model_version': 'YOLOv11',
            'confidence_threshold': 0.25,
            'original_path': original,
            'annotated_path': annotated,
            'image_width': 640,
            'image_height': 480,
            'detection_count': 1,
            'class_counts': {'03-裂纹': 1},
            'detections': [{
                'class_name': '03-裂纹',
                'confidence': 0.92,
                'box': [10, 20, 80, 90],
            }],
            'ai_review': {'status': 'completed', 'model': 'kimi-k3'},
            'conclusion': '发现 1 个候选缺陷。',
            'disclaimer': '需人工复核。',
        })
        self.record_ids.append(record_id)
        return record

    def test_overview_and_selected_exports(self):
        record = self.create_record()
        overview = self.manager.overview()
        self.assertEqual(overview['database']['engine'], 'MySQL')
        self.assertTrue(overview['database']['connected'])
        self.assertGreaterEqual(overview['database']['total_records'], 1)
        self.assertEqual(overview['storage']['records']['files'], 2)
        self.assertEqual(overview['storage']['records']['bytes'], 29)

        json_export = json.loads(
            self.manager.build_json_export([record['id']])
            .getvalue()
            .decode('utf-8')
        )
        self.assertEqual(json_export['record_count'], 1)
        exported_record = json_export['records'][0]
        self.assertNotIn('original_path', exported_record)
        self.assertNotIn('annotated_path', exported_record)
        self.assertEqual(exported_record['id'], record['id'])

        with zipfile.ZipFile(
            self.manager.build_zip_export([record['id']])
        ) as archive:
            names = set(archive.namelist())
        self.assertIn('weldsight-export.json', names)
        self.assertIn(
            f"records/{record['id']}/original.jpg",
            names,
        )
        self.assertIn(
            f"records/{record['id']}/annotated.jpg",
            names,
        )

    def test_exact_delete_updates_batch_and_removes_files(self):
        batch = self.store.create_batch('数据管理测试批次', 1)
        self.batch_ids.append(batch['id'])
        record = self.create_record(batch_id=batch['id'])
        self.store.update_batch(
            batch['id'],
            status='completed',
            processed=1,
            completed=1,
            record_ids=[record['id']],
        )

        result = self.manager.delete_records([record['id']])

        self.assertEqual(result['deleted_records'], 1)
        self.assertGreater(result['reclaimed_bytes'], 0)
        self.assertIsNone(self.store.get_inspection(record['id']))
        self.assertFalse((self.record_root / record['id']).exists())
        self.assertEqual(
            self.store.get_batch(batch['id'])['record_ids'],
            [],
        )

    def test_cleanup_only_removes_orphan_directories(self):
        record = self.create_record()
        orphan_record = self.record_root / f'orphan-{uuid4().hex[:8]}'
        orphan_batch = self.batch_root / f'orphan-{uuid4().hex[:8]}'
        orphan_record.mkdir(parents=True)
        orphan_batch.mkdir(parents=True)
        (orphan_record / 'unused.jpg').write_bytes(b'orphan')
        (orphan_batch / 'input.jpg').write_bytes(b'orphan-batch')

        result = self.manager.cleanup_orphans()

        self.assertEqual(result['removed_directories'], 2)
        self.assertGreater(result['reclaimed_bytes'], 0)
        self.assertFalse(orphan_record.exists())
        self.assertFalse(orphan_batch.exists())
        self.assertTrue((self.record_root / record['id']).exists())


if __name__ == '__main__':
    unittest.main()
