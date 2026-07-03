import os
from flask import Flask
from app.config import Config
from app.model_manager import load_yolo_model
from app.camera_handler import init_camera_global_vars
from app.video_processor import init_video_global_vars
from app.routes import main_bp, image_bp, video_bp, camera_bp

def create_app(config_class=Config):
    # 1. 创建Flask实例
    app = Flask(
        __name__,
        static_folder='../static',
        static_url_path=''
    )
    app.config.from_object(config_class)  # 加载配置

    # 2. 初始化必要目录（上传目录）
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # 3. 初始化全局变量
    app.model = load_yolo_model(app.config['MODEL_PATH'])  # 加载YOLO模型
    # ✅ 修改：传入app.config中的默认摄像头索引，不再让函数内部访问current_app
    app.camera_vars = init_camera_global_vars(app.config['CAMERA_DEFAULT_INDEX'])
    app.video_vars = init_video_global_vars()              # 视频进度全局变量

    # 4. 注册路由蓝图
    app.register_blueprint(main_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(camera_bp)

    # 5. 打印初始化日志
    print(f"✅ Flask应用初始化完成 | 模型状态: {'已加载' if app.model else '未加载'}")
    print(f"✅ 上传目录: {app.config['UPLOAD_FOLDER']}")

    return app