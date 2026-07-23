import os
from datetime import datetime

from flask import Flask

from app.ai_reviewer import KimiVisionReviewer
from app.camera_handler import init_camera_global_vars
from app.config import Config
from app.inspection_service import InspectionService
from app.inspection_store import InspectionStore
from app.model_manager import load_yolo_model
from app.routes import (
    camera_bp,
    image_bp,
    inspection_bp,
    main_bp,
    video_bp,
)
from app.video_processor import init_video_global_vars


def _build_ai_reviewer(app):
    return KimiVisionReviewer(
        api_key=app.config['MOONSHOT_API_KEY'],
        model=app.config['KIMI_VISION_MODEL'],
        fallback_models=app.config['KIMI_FALLBACK_MODELS'],
        base_url=app.config['KIMI_BASE_URL'],
        timeout=app.config['KIMI_TIMEOUT_SECONDS'],
        max_retries=app.config['KIMI_MAX_RETRIES'],
        retry_base_seconds=app.config['KIMI_RETRY_BASE_SECONDS'],
    )


def create_app(config_class=Config):
    app = Flask(__name__, static_folder='../static', static_url_path='')
    app.config.from_object(config_class)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RECORD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['BATCH_FOLDER'], exist_ok=True)

    app.model = load_yolo_model(app.config['MODEL_PATH'])
    app.inspection_store = InspectionStore(
        app.config['DATABASE_PATH'],
        app.config['DATA_FOLDER'],
    )
    app.settings_defaults = {
        'project_name': app.config['PROJECT_NAME'],
        'organization': app.config['ORGANIZATION'],
        'default_reviewer': app.config['DEFAULT_REVIEWER'],
        'conf_thresh': app.config['CONF_THRESH'],
        'kimi_review_enabled': app.config['KIMI_REVIEW_ENABLED'],
        'kimi_model': app.config['KIMI_VISION_MODEL'],
        'kimi_fallback_models': app.config['KIMI_FALLBACK_MODELS'],
        'kimi_max_retries': app.config['KIMI_MAX_RETRIES'],
        'camera_default_index': app.config['CAMERA_DEFAULT_INDEX'],
        'alert_cooldown_seconds': app.config['ALERT_COOLDOWN_SECONDS'],
    }

    def apply_runtime_settings():
        settings = app.inspection_store.get_settings(app.settings_defaults)
        app.config['CONF_THRESH'] = float(settings['conf_thresh'])
        app.config['KIMI_REVIEW_ENABLED'] = bool(
            settings['kimi_review_enabled']
        )
        app.config['KIMI_VISION_MODEL'] = settings['kimi_model']
        app.config['KIMI_FALLBACK_MODELS'] = settings[
            'kimi_fallback_models'
        ]
        app.config['KIMI_MAX_RETRIES'] = int(
            settings['kimi_max_retries']
        )
        app.config['CAMERA_DEFAULT_INDEX'] = int(
            settings['camera_default_index']
        )
        app.config['ALERT_COOLDOWN_SECONDS'] = int(
            settings['alert_cooldown_seconds']
        )
        app.ai_reviewer = _build_ai_reviewer(app)
        if hasattr(app, 'camera_vars'):
            app.camera_vars['alert_cooldown_seconds'] = app.config[
                'ALERT_COOLDOWN_SECONDS'
            ]
        return settings

    app.apply_runtime_settings = apply_runtime_settings
    app.apply_runtime_settings()
    app.camera_vars = init_camera_global_vars(
        app.config['CAMERA_DEFAULT_INDEX']
    )
    app.video_vars = init_video_global_vars()
    app.inspection_service = InspectionService(app, app.inspection_store)

    def record_camera_alert(
        original_jpeg,
        annotated_jpeg,
        detections,
        image_width,
        image_height,
    ):
        settings = app.inspection_store.get_settings(app.settings_defaults)
        return app.inspection_service.save_result(
            original_jpeg=original_jpeg,
            annotated_jpeg=annotated_jpeg,
            detections=detections,
            source_name=(
                'camera-alert-'
                + datetime.now().strftime('%Y%m%d-%H%M%S')
                + '.jpg'
            ),
            source_type='camera',
            confidence_threshold=app.config['CONF_THRESH'],
            image_width=image_width,
            image_height=image_height,
            project_name=settings.get('project_name', ''),
            reviewer=settings.get('default_reviewer', ''),
            queue_ai=False,
        )

    app.camera_vars['alert_recorder'] = record_camera_alert
    app.camera_vars['alert_cooldown_seconds'] = app.config[
        'ALERT_COOLDOWN_SECONDS'
    ]

    app.register_blueprint(main_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(inspection_bp)

    app.logger.info(
        'WeldSight initialized: model=%s, kimi_review=%s, database=%s',
        'loaded' if app.model else 'unavailable',
        'ready' if app.ai_reviewer.available else 'not_configured',
        app.config['DATABASE_PATH'],
    )
    return app
