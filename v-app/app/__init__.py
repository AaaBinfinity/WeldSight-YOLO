import os

from flask import Flask

from app.ai_reviewer import KimiVisionReviewer
from app.camera_handler import init_camera_global_vars
from app.config import Config
from app.model_manager import load_yolo_model
from app.routes import camera_bp, image_bp, main_bp, video_bp
from app.video_processor import init_video_global_vars


def create_app(config_class=Config):
    app = Flask(__name__, static_folder='../static', static_url_path='')
    app.config.from_object(config_class)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    app.model = load_yolo_model(app.config['MODEL_PATH'])
    app.camera_vars = init_camera_global_vars(app.config['CAMERA_DEFAULT_INDEX'])
    app.video_vars = init_video_global_vars()
    app.ai_reviewer = KimiVisionReviewer(
        api_key=app.config['MOONSHOT_API_KEY'],
        model=app.config['KIMI_VISION_MODEL'],
        fallback_models=app.config['KIMI_FALLBACK_MODELS'],
        base_url=app.config['KIMI_BASE_URL'],
        timeout=app.config['KIMI_TIMEOUT_SECONDS'],
        max_retries=app.config['KIMI_MAX_RETRIES'],
        retry_base_seconds=app.config['KIMI_RETRY_BASE_SECONDS'],
    )

    app.register_blueprint(main_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(camera_bp)

    app.logger.info(
        'WeldSight initialized: model=%s, kimi_review=%s',
        'loaded' if app.model else 'unavailable',
        'ready' if app.ai_reviewer.available else 'not_configured',
    )
    return app
