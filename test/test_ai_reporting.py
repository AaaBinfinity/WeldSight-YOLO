import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import APITimeoutError, RateLimitError
from PIL import Image
from pypdf import PdfReader


APP_ROOT = Path(__file__).resolve().parents[1] / 'v-app' / 'app'
sys.path.insert(0, str(APP_ROOT.parent))
APP_PACKAGE = ModuleType('app')
APP_PACKAGE.__path__ = [str(APP_ROOT)]
sys.modules.setdefault('app', APP_PACKAGE)


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


KimiVisionReviewer = load_module('ai_reviewer').KimiVisionReviewer
build_detection_report = load_module('reporting').build_detection_report
DEFECT_CLASSES = load_module('defect_classes')
render_annotated_image = load_module(
    'annotation_renderer'
).render_annotated_image
PDF_REPORTS = load_module('pdf_reports')


class AnnotationColorTests(unittest.TestCase):
    def test_all_defect_classes_have_distinct_colors(self):
        colors = [
            DEFECT_CLASSES.defect_color(class_id)
            for class_id in range(7)
        ]
        self.assertEqual(len(set(colors)), 7)

    def test_annotation_renderer_uses_class_colors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.png'
            Image.new('RGB', (100, 100), 'white').save(source)
            rendered = render_annotated_image(source, [
                {'class_id': 0, 'box_xyxy': [5, 20, 30, 45]},
                {'class_id': 2, 'box_xyxy': [50, 60, 80, 90]},
            ])
            self.assertEqual(rendered.getpixel((5, 30)), (47, 123, 255))
            self.assertEqual(rendered.getpixel((50, 70)), (239, 51, 64))


class PdfReportTests(unittest.TestCase):
    @staticmethod
    def _record(image_path):
        return {
            'id': '1234567890abcdef1234567890abcdef',
            'created_at': '2026-07-23T10:00:00+00:00',
            'updated_at': '2026-07-23T10:00:00+00:00',
            'source_type': 'image',
            'source_name': 'sample.jpg',
            'status': 'completed',
            'ai_status': 'completed',
            'model_name': 'best_v8.pt',
            'model_version': 'YOLOv11',
            'confidence_threshold': 0.25,
            'original_path': str(image_path),
            'annotated_path': str(image_path),
            'image_width': 640,
            'image_height': 360,
            'detection_count': 2,
            'class_counts': {'03-裂纹': 1, '07-未熔合': 1},
            'detections': [
                {
                    'class_id': 2,
                    'class_name': '03-裂纹',
                    'confidence': 0.91,
                    'box_xyxy': [40, 50, 220, 190],
                },
                {
                    'class_id': 6,
                    'class_name': '07-未熔合',
                    'confidence': 0.82,
                    'box_xyxy': [300, 90, 520, 230],
                },
            ],
            'ai_review': {
                'status': 'completed',
                'risk_level': 'high',
                'summary': '发现裂纹与未熔合候选缺陷，建议人工复核。',
                'confirmed_findings': [{
                    'class_name': '03-裂纹',
                    'reason': '线性影像特征明显。',
                }],
                'possible_false_positives': [],
                'possible_missed_defects': [],
                'recommendations': ['结合原始底片确认缺陷边界。'],
            },
            'conclusion': '检测到 2 处候选缺陷。',
            'disclaimer': '仅用于辅助筛查。',
            'project_name': 'PDF 回归测试',
            'reviewer': '测试员',
            'review_decision': 'mixed',
            'review_notes': '已复核检测结果。',
            'corrections': [
                {
                    'detection_index': 0,
                    'decision': 'confirmed',
                    'original_class_name': '03-裂纹',
                    'class_name': '03-裂纹',
                },
                {
                    'detection_index': 1,
                    'decision': 'class_changed',
                    'original_class_name': '07-未熔合',
                    'class_name': '05-内凹',
                },
            ],
            'missed_defects': [
                {'suspected_type': '03-裂纹'},
                {'suspected_type': '06-圆缺（夹钨）'},
            ],
            'reviewed_at': '2026-07-23T10:05:00+00:00',
        }

    def test_inspection_pdf_is_paginated_and_extractable(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / 'source.jpg'
            Image.new('RGB', (640, 360), '#1a222b').save(image_path)
            output = PDF_REPORTS.build_inspection_pdf(
                self._record(image_path),
                {'organization': '测试机构'},
            )
            self.assertTrue(output.getvalue().startswith(b'%PDF-'))
            reader = PdfReader(output)
            self.assertGreaterEqual(len(reader.pages), 4)
            text = ''.join(page.extract_text() or '' for page in reader.pages)
            self.assertIn('焊缝缺陷质检报告', text)
            self.assertIn('YOLO 候选缺陷明细', text)
            self.assertIn('人工复核与处置', text)
            self.assertIn('人工漏检登记', text)
            self.assertIn('检测历史页面已登记 2 项', text)
            self.assertIn('03-裂纹', text)
            self.assertIn('06-圆缺（夹钨）', text)
            self.assertIn('已检出框逐项复核', text)
            self.assertIn('原检测类别', text)
            self.assertIn('确认框正确', text)
            self.assertIn('修改类别', text)
            self.assertIn('人工确认类别', text)
            self.assertNotIn('人工修正记录', text)

    def test_batch_pdf_contains_summary_and_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / 'source.jpg'
            Image.new('RGB', (640, 360), '#1a222b').save(image_path)
            record = self._record(image_path)
            output = PDF_REPORTS.build_batch_pdf(
                {
                    'id': 'abcdef1234567890abcdef1234567890',
                    'name': 'PDF 回归批次',
                    'status': 'completed',
                    'total': 1,
                    'completed': 1,
                    'failed': 0,
                    'created_at': '2026-07-23T10:00:00+00:00',
                    'updated_at': '2026-07-23T10:05:00+00:00',
                },
                [record],
                {'organization': '测试机构'},
            )
            self.assertTrue(output.getvalue().startswith(b'%PDF-'))
            reader = PdfReader(output)
            self.assertGreaterEqual(len(reader.pages), 2)
            text = ''.join(page.extract_text() or '' for page in reader.pages)
            self.assertIn('批量焊缝检测汇总报告', text)
            self.assertIn('sample.jpg', text)

    def test_accepted_pdf_suppresses_stale_missed_defect_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / 'source.jpg'
            Image.new('RGB', (640, 360), '#1a222b').save(image_path)
            record = self._record(image_path)
            record['review_decision'] = 'accepted'
            record['corrections'] = [
                {
                    'detection_index': index,
                    'decision': 'confirmed',
                    'original_class_name': detection['class_name'],
                    'class_name': detection['class_name'],
                }
                for index, detection in enumerate(record['detections'])
            ]
            output = PDF_REPORTS.build_inspection_pdf(
                record,
                {'organization': '测试机构'},
            )
            text = ''.join(
                page.extract_text() or ''
                for page in PdfReader(output).pages
            )
            self.assertIn('当前人工结论（结果接受）不包含漏检登记', text)
            self.assertNotIn('检测历史页面已登记 2 项', text)


class AiReviewerTests(unittest.TestCase):
    def test_missing_key_returns_degraded_status(self):
        reviewer = KimiVisionReviewer(api_key='')
        result = reviewer.review(b'original', b'annotated', [])
        self.assertEqual(result['status'], 'not_configured')

    def test_multimodal_request_uses_content_array(self):
        reviewer = KimiVisionReviewer(api_key='')
        reviewer.available = True
        reviewer.client = Mock()
        reviewer.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({
                            'overall_assessment': 'uncertain',
                            'risk_level': 'medium',
                            'summary': '需要人工复核。',
                        }, ensure_ascii=False)
                    )
                )
            ]
        )
        result = reviewer.review(
            b'original',
            b'annotated',
            [{'class_name': 'pore', 'confidence': 0.8}],
        )
        kwargs = reviewer.client.chat.completions.create.call_args.kwargs
        content = kwargs['messages'][1]['content']
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]['type'], 'image_url')
        self.assertEqual(content[1]['type'], 'image_url')
        self.assertEqual(content[2]['type'], 'text')
        self.assertEqual(result['status'], 'completed')

    def test_transient_error_retries_then_succeeds(self):
        sleep = Mock()
        reviewer = KimiVisionReviewer(
            api_key='test-only',
            max_retries=2,
            retry_base_seconds=0.01,
            sleep=sleep,
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({
                            'overall_assessment': 'uncertain',
                            'risk_level': 'medium',
                            'summary': '重试后完成。',
                        }, ensure_ascii=False)
                    )
                )
            ]
        )
        reviewer.client = Mock()
        reviewer.client.chat.completions.create.side_effect = [
            APITimeoutError(request=httpx.Request('POST', 'https://example.test')),
            response,
        ]
        result = reviewer.review(b'original', b'annotated', [])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(
            reviewer.client.chat.completions.create.call_count,
            2,
        )
        sleep.assert_called_once_with(0.01)

    def test_rate_limit_overload_retries_without_blocking_yolo_result(self):
        sleep = Mock()
        reviewer = KimiVisionReviewer(
            api_key='test-only',
            max_retries=2,
            retry_base_seconds=0.01,
            sleep=sleep,
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({
                            'overall_assessment': 'uncertain',
                            'risk_level': 'medium',
                            'summary': '429 重试后完成。',
                        }, ensure_ascii=False)
                    )
                )
            ]
        )
        request = httpx.Request('POST', 'https://example.test')
        reviewer.client = Mock()
        reviewer.client.chat.completions.create.side_effect = [
            RateLimitError(
                'The engine is currently overloaded',
                response=httpx.Response(429, request=request),
                body={'error': {'type': 'engine_overloaded_error'}},
            ),
            response,
        ]
        result = reviewer.review(b'original', b'annotated', [])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(
            reviewer.client.chat.completions.create.call_count,
            2,
        )
        sleep.assert_called_once_with(0.01)


class ReportTests(unittest.TestCase):
    def test_report_contains_yolo_and_fallback_conclusion(self):
        report = build_detection_report(
            [{'class_name': 'pore', 'confidence': 0.8}],
            {'status': 'not_configured'},
        )
        self.assertEqual(report['yolo']['detection_count'], 1)
        self.assertEqual(report['yolo']['class_counts'], {'pore': 1})
        self.assertIn('专业人员复核', report['conclusion'])
        self.assertTrue(report['report_id'])

    def test_numeric_model_class_is_exposed_as_numbered_chinese_label(self):
        report = build_detection_report(
            [{'class_id': 2, 'class_name': '03', 'confidence': 0.91}],
            {'status': 'not_configured'},
        )
        self.assertEqual(
            report['yolo']['class_counts'],
            {'03-裂纹': 1},
        )
        self.assertEqual(
            report['yolo']['detections'][0]['class_name'],
            '03-裂纹',
        )

    def test_ai_free_text_defect_type_is_folded_into_allowed_classes(self):
        report = build_detection_report(
            [],
            {
                'status': 'completed',
                'possible_missed_defects': [{
                    'suspected_type': '点状缺陷（气孔/夹渣）',
                }],
            },
        )
        self.assertEqual(
            report['ai_review']['possible_missed_defects'][0][
                'suspected_type'
            ],
            '01-未焊透加气孔',
        )

    def test_human_review_decision_rejects_invalid_missed_defect_combinations(self):
        validate = DEFECT_CLASSES.validate_missed_defect_selection
        missed = [{'suspected_type': '03-裂纹'}]
        self.assertIn('不能登记漏检', validate('accepted', missed))
        self.assertIn('至少选择', validate('missed_defect', []))
        self.assertEqual(validate('missed_defect', missed), '')
        self.assertEqual(validate('mixed', missed), '')

    def test_detection_reviews_are_complete_and_class_changes_are_real(self):
        detections = [
            {'class_id': 1, 'class_name': '02', 'confidence': 0.8},
            {'class_id': 2, 'class_name': '03', 'confidence': 0.9},
        ]
        normalized, error = DEFECT_CLASSES.normalize_detection_reviews(
            detections,
            [
                {
                    'detection_index': 0,
                    'decision': 'confirmed',
                    'class_name': '07-未熔合',
                },
                {
                    'detection_index': 1,
                    'decision': 'class_changed',
                    'class_name': '05-内凹',
                },
            ],
        )
        self.assertEqual(error, '')
        self.assertEqual(normalized[0]['class_name'], '02-圆缺')
        self.assertEqual(
            normalized[0]['original_class_name'],
            '02-圆缺',
        )
        self.assertEqual(normalized[1]['class_name'], '05-内凹')

        _, incomplete_error = DEFECT_CLASSES.normalize_detection_reviews(
            detections,
            [],
        )
        self.assertIn('每个已检出框', incomplete_error)

        _, same_class_error = DEFECT_CLASSES.normalize_detection_reviews(
            detections,
            [
                {
                    'detection_index': 0,
                    'decision': 'confirmed',
                    'class_name': '02-圆缺',
                },
                {
                    'detection_index': 1,
                    'decision': 'class_changed',
                    'class_name': '03-裂纹',
                },
            ],
        )
        self.assertIn('不能与原检测类别相同', same_class_error)

    def test_overall_review_decision_must_match_box_reviews(self):
        validate = DEFECT_CLASSES.validate_human_review_consistency
        confirmed = [{
            'detection_index': 0,
            'decision': 'confirmed',
            'class_name': '02-圆缺',
        }]
        false_positive = [{
            'detection_index': 0,
            'decision': 'false_positive',
            'class_name': '02-圆缺',
        }]
        self.assertIn(
            '所有已检出框',
            validate('accepted', false_positive, []),
        )
        self.assertIn(
            '至少将一个检测框',
            validate('false_positive', confirmed, []),
        )
        self.assertEqual(
            validate('false_positive', false_positive, []),
            '',
        )


if __name__ == '__main__':
    unittest.main()
