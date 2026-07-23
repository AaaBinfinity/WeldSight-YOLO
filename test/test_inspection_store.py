import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / 'v-app'
STORE_PATH = APP_ROOT / 'app' / 'inspection_store.py'
STORE_SPEC = importlib.util.spec_from_file_location(
    'weldsight_inspection_store',
    STORE_PATH,
)
STORE_MODULE = importlib.util.module_from_spec(STORE_SPEC)
STORE_SPEC.loader.exec_module(STORE_MODULE)
InspectionStore = STORE_MODULE.InspectionStore


class InspectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = InspectionStore(root / 'weldsight.db', root / 'data')
        self.original = root / 'original.jpg'
        self.annotated = root / 'annotated.jpg'
        self.original.write_bytes(b'original')
        self.annotated.write_bytes(b'annotated')

    def tearDown(self):
        self.temporary.cleanup()

    def create_record(self, **overrides):
        payload = {
            'source_type': 'image',
            'source_name': 'sample.jpg',
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
        return self.store.create_inspection(payload)

    def test_record_search_review_and_training_feedback(self):
        record = self.create_record()
        result = self.store.list_inspections(query='裂纹')
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
        updated = self.store.update_batch(
            batch['id'],
            status='processing',
            processed=1,
            completed=1,
        )
        self.assertEqual(updated['progress'], 50.0)

        self.store.update_settings({
            'conf_thresh': 0.42,
            'kimi_review_enabled': False,
        })
        settings = self.store.get_settings({'conf_thresh': 0.25})
        self.assertEqual(settings['conf_thresh'], 0.42)
        self.assertFalse(settings['kimi_review_enabled'])

        analytics = self.store.analytics(30)
        self.assertEqual(analytics['total_inspections'], 2)
        self.assertEqual(analytics['defect_records'], 1)
        self.assertEqual(
            analytics['class_distribution'],
            [{'name': '裂纹', 'value': 1}],
        )


if __name__ == '__main__':
    unittest.main()
