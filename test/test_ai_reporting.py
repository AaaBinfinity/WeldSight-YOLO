import json
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import APITimeoutError, RateLimitError


APP_ROOT = Path(__file__).resolve().parents[1] / 'v-app' / 'app'


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


KimiVisionReviewer = load_module('ai_reviewer').KimiVisionReviewer
build_detection_report = load_module('reporting').build_detection_report


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


if __name__ == '__main__':
    unittest.main()
