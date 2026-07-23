"""Kimi vision review for YOLO weld-defect detections."""

import base64
import json
import time
from collections import Counter

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)


SYSTEM_PROMPT = """你是工业射线检测辅助复核模型。
你需要结合两张图片进行谨慎复核：第一张是原始焊缝射线底片，第二张是 YOLO 标注结果。
YOLO 的框和类别只是候选，不是事实。请指出支持、疑似误报、可能漏检和图像质量问题。
不要声称替代持证无损检测人员，也不要给出无法从图像支持的确定性结论。
必须输出一个 JSON 对象，不要输出 Markdown。"""

TRANSIENT_ERRORS = (
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)


def _data_url(jpeg_bytes):
    encoded = base64.b64encode(jpeg_bytes).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


def _summary(detections):
    counts = Counter(item['class_name'] for item in detections)
    return {
        'total': len(detections),
        'by_class': dict(sorted(counts.items())),
        'detections': detections,
    }


def _unique_models(primary, fallbacks):
    result = []
    for model in [primary, *fallbacks]:
        model = model.strip()
        if model and model not in result:
            result.append(model)
    return result


class KimiVisionReviewer:
    def __init__(
        self,
        api_key,
        model='kimi-k3',
        fallback_models=None,
        base_url='https://api.moonshot.cn/v1',
        timeout=60,
        max_retries=3,
        retry_base_seconds=2,
        sleep=time.sleep,
    ):
        self.model = model
        self.models = _unique_models(model, fallback_models or [])
        self.max_retries = max(1, int(max_retries))
        self.retry_base_seconds = max(0, float(retry_base_seconds))
        self.sleep = sleep
        self.available = bool(api_key)
        self.client = (
            OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
            )
            if self.available else None
        )

    def _create_completion(self, model, messages):
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return self.client.chat.completions.create(
                    model=model,
                    response_format={'type': 'json_object'},
                    messages=messages,
                )
            except TRANSIENT_ERRORS as exc:
                last_error = exc
                if attempt + 1 >= self.max_retries:
                    break
                delay = self.retry_base_seconds * (2 ** attempt)
                if delay:
                    self.sleep(delay)
        raise last_error

    def review(self, original_jpeg, annotated_jpeg, detections):
        """Review original and annotated images and return normalized report data."""
        if not self.available:
            return {
                'status': 'not_configured',
                'message': '未配置 MOONSHOT_API_KEY，已跳过 Kimi 视觉复核。',
            }

        prompt = f"""YOLO 候选结果如下：
{json.dumps(_summary(detections), ensure_ascii=False)}

请按以下字段输出 JSON：
{{
  "overall_assessment": "supported|uncertain|not_supported|no_defect",
  "risk_level": "low|medium|high",
  "confirmed_findings": [{{"class_name":"", "reason":"", "confidence":"low|medium|high"}}],
  "possible_false_positives": [{{"class_name":"", "reason":""}}],
  "possible_missed_defects": [{{"suspected_type":"", "location_description":"", "reason":""}}],
  "image_quality": {{"status":"good|fair|poor", "issues":[]}},
  "recommendations": [],
  "summary": "面向用户的简短中文总结"
}}"""
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {'url': _data_url(original_jpeg)},
                    },
                    {
                        'type': 'image_url',
                        'image_url': {'url': _data_url(annotated_jpeg)},
                    },
                    {'type': 'text', 'text': prompt},
                ],
            },
        ]

        last_error = None
        for model in self.models:
            try:
                response = self._create_completion(model, messages)
                content = response.choices[0].message.content or '{}'
                parsed = json.loads(content)
                parsed['status'] = 'completed'
                parsed['model'] = model
                return parsed
            except TRANSIENT_ERRORS as exc:
                last_error = exc

        raise last_error
