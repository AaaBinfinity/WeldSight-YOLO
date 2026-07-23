import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / '.env')


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_path(name, default):
    path = Path(os.environ.get(name, default))
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def env_list(name, default=''):
    return [
        item.strip()
        for item in os.environ.get(name, default).split(',')
        if item.strip()
    ]


class Config:
    """Application configuration loaded from environment variables and .env."""

    BASE_DIR = str(PROJECT_ROOT / 'v-app')
    UPLOAD_FOLDER = str(PROJECT_ROOT / 'v-app' / 'uploads')
    DATA_FOLDER = env_path('WELDSIGHT_DATA_FOLDER', 'v-app/data')
    RECORD_FOLDER = env_path(
        'WELDSIGHT_RECORD_FOLDER',
        'v-app/data/records',
    )
    BATCH_FOLDER = env_path(
        'WELDSIGHT_BATCH_FOLDER',
        'v-app/data/batches',
    )
    DATABASE_CONFIG = {
        'host': os.environ.get('MYSQL_HOST', 'localhost'),
        'port': int(os.environ.get('MYSQL_PORT', '3306')),
        'user': os.environ.get('MYSQL_USER', 'root'),
        'password': os.environ.get('MYSQL_PASSWORD', ''),
        'database': os.environ.get('MYSQL_DATABASE', 'WeldSight'),
        'connect_timeout': int(
            os.environ.get('MYSQL_CONNECT_TIMEOUT', '10')
        ),
    }
    MODEL_PATH = env_path(
        'YOLO_MODEL_PATH',
        'v-app/best_v8.pt',
    )

    CONF_THRESH = float(os.environ.get('CONF_THRESH', '0.25'))
    YOLO_MODEL_VERSION = os.environ.get('YOLO_MODEL_VERSION', 'YOLOv11')
    CAMERA_DEFAULT_INDEX = int(os.environ.get('CAMERA_DEFAULT_INDEX', '0'))
    ALERT_COOLDOWN_SECONDS = int(
        os.environ.get('ALERT_COOLDOWN_SECONDS', '8')
    )
    BATCH_MAX_IMAGES = int(os.environ.get('BATCH_MAX_IMAGES', '50'))
    VIDEO_MAX_PROGRESS_CACHE = int(
        os.environ.get('VIDEO_MAX_PROGRESS_CACHE', '30')
    )

    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev_123456')
    JSON_SORT_KEYS = False

    MOONSHOT_API_KEY = os.environ.get('MOONSHOT_API_KEY', '')
    KIMI_REVIEW_ENABLED = env_bool('KIMI_REVIEW_ENABLED', True)
    KIMI_VISION_MODEL = os.environ.get('KIMI_VISION_MODEL', 'kimi-k3')
    KIMI_FALLBACK_MODELS = env_list(
        'KIMI_FALLBACK_MODELS',
        'moonshot-v1-32k-vision-preview,kimi-k2.6',
    )
    KIMI_BASE_URL = os.environ.get(
        'KIMI_BASE_URL',
        'https://api.moonshot.cn/v1',
    )
    KIMI_TIMEOUT_SECONDS = float(
        os.environ.get('KIMI_TIMEOUT_SECONDS', '60')
    )
    KIMI_MAX_RETRIES = int(os.environ.get('KIMI_MAX_RETRIES', '2'))
    KIMI_RETRY_BASE_SECONDS = float(
        os.environ.get('KIMI_RETRY_BASE_SECONDS', '1')
    )

    PROJECT_NAME = os.environ.get(
        'WELDSIGHT_PROJECT_NAME',
        '焊缝质量检测',
    )
    ORGANIZATION = os.environ.get('WELDSIGHT_ORGANIZATION', '')
    DEFAULT_REVIEWER = os.environ.get('WELDSIGHT_DEFAULT_REVIEWER', '')
