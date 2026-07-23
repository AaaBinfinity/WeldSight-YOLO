import json
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / 'v-app'
load_dotenv(PROJECT_ROOT / '.env')
sys.path.insert(0, str(APP_ROOT))
APP_PACKAGE = ModuleType('app')
APP_PACKAGE.__path__ = [str(APP_ROOT / 'app')]
sys.modules.setdefault('app', APP_PACKAGE)
STORE_PATH = APP_ROOT / 'app' / 'inspection_store.py'
STORE_SPEC = importlib.util.spec_from_file_location(
    'weldsight_inspection_store',
    STORE_PATH,
)
STORE_MODULE = importlib.util.module_from_spec(STORE_SPEC)
STORE_SPEC.loader.exec_module(STORE_MODULE)
InspectionStore = STORE_MODULE.InspectionStore
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'localhost'),
    'port': int(os.environ.get('MYSQL_PORT', '3306')),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'database': os.environ.get('MYSQL_DATABASE', 'WeldSight'),
    'connect_timeout': int(os.environ.get('MYSQL_CONNECT_TIMEOUT', '10')),
}


class InspectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = InspectionStore(MYSQL_CONFIG, root / 'data')
        self.test_prefix = f'test-{uuid4().hex}'
        self.record_ids = []
        self.batch_ids = []
        self.setting_keys = []
        self.analytics_before = self.store.analytics(30)
        self.original = root / 'original.jpg'
        self.annotated = root / 'annotated.jpg'
        self.original.write_bytes(b'original')
        self.annotated.write_bytes(b'annotated')

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
                for key in self.setting_keys:
                    connection.execute(
                        'DELETE FROM settings WHERE `key` = ?',
                        (key,),
                    )
        finally:
            self.temporary.cleanup()

    def create_record(self, **overrides):
        payload = {
            'id': uuid4().hex,
            'source_type': 'image',
            'source_name': f'{self.test_prefix}-sample.jpg',
            'status': 'completed',
            'ai_status': 'completed',
            'model_name': 'best.pt',
            'model_version': 'YOLOv11',
            'confidence_threshold': 0.25,
            'original_path': self.original,
            'annotated_path': self.annotated,
            'image_width': 640,
            'image_height': 480,
            'detection_count': 1,
            'class_counts': {'裂纹': 1},
            'detections': [{
                'class_name': '裂纹',
                'confidence': 0.91,
                'box': [10, 20, 80, 90],
            }],
            'ai_review': {'status': 'completed', 'model': 'kimi-k3'},
            'conclusion': '发现 1 个候选缺陷。',
            'disclaimer': '需人工复核。',
            'project_name': '演示项目',
            'reviewer': '',
        }
        payload.update(overrides)
        record = self.store.create_inspection(payload)
        self.record_ids.append(record['id'])
        return record

    def test_record_search_review_and_training_feedback(self):
        record = self.create_record()
        result = self.store.list_inspections(query=self.test_prefix)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], record['id'])

        reviewed = self.store.save_human_review(
            record_id=record['id'],
            decision='confirmed',
            reviewer='张工',
            notes='建议返修后复拍。',
            corrections=[{
                'detection_index': 0,
                'decision': 'confirmed',
                'class_name': '裂纹',
            }],
            missed_defects=[],
        )
        self.assertEqual(reviewed['status'], 'reviewed')
        self.assertEqual(reviewed['review_decision'], 'confirmed')
        feedback = [
            json.loads(line)
            for line in self.store.feedback_path.read_text(
                encoding='utf-8'
            ).splitlines()
        ]
        self.assertEqual(feedback[0]['inspection_id'], record['id'])
        self.assertEqual(feedback[0]['reviewer'], '张工')

    def test_batches_settings_and_analytics(self):
        self.create_record()
        self.create_record(
            source_type='camera',
            source_name='camera-alert.jpg',
            detection_count=0,
            class_counts={},
            detections=[],
        )
        batch = self.store.create_batch('夜班抽检', 2)
        self.batch_ids.append(batch['id'])
        updated = self.store.update_batch(
            batch['id'],
            status='processing',
            processed=1,
            completed=1,
        )
        self.assertEqual(updated['progress'], 50.0)

        conf_key = f'{self.test_prefix}-conf-thresh'
        kimi_key = f'{self.test_prefix}-kimi-enabled'
        self.setting_keys.extend([conf_key, kimi_key])
        self.store.update_settings({
            conf_key: 0.42,
            kimi_key: False,
        })
        settings = self.store.get_settings({conf_key: 0.25})
        self.assertEqual(settings[conf_key], 0.42)
        self.assertFalse(settings[kimi_key])

        analytics = self.store.analytics(30)
        self.assertEqual(
            analytics['total_inspections'],
            self.analytics_before['total_inspections'] + 2,
        )
        self.assertEqual(
            analytics['defect_records'],
            self.analytics_before['defect_records'] + 1,
        )
        before_classes = {
            item['name']: item['value']
            for item in self.analytics_before['class_distribution']
        }
        after_classes = {
            item['name']: item['value']
            for item in analytics['class_distribution']
        }
        self.assertEqual(
            after_classes.get('03-裂纹', 0),
            before_classes.get('03-裂纹', 0) + 1,
        )


if __name__ == '__main__':
    unittest.main()
