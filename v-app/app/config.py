import os

class Config:
    """基础配置类"""
    # 路径配置
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))  # 项目根目录
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')                          # 上传目录
    MODEL_PATH = os.path.join(BASE_DIR, 'best_v8.pt')                          # YOLO模型路径

    # 检测配置
    CONF_THRESH = 0.25   
    CAMERA_DEFAULT_INDEX = 0 
    VIDEO_MAX_PROGRESS_CACHE = 30  # 视频进度缓存时间（秒）

    # Flask配置
    SECRET_KEY = 'dev_123456' 
    JSON_SORT_KEYS = False 