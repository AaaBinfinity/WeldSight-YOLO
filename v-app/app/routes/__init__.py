from flask import Blueprint

# 创建各功能模块的路由蓝图
main_bp = Blueprint('main', __name__)       # 首页与基础状态
image_bp = Blueprint('image', __name__)     # 图片检测相关接口
video_bp = Blueprint('video', __name__)     # 视频处理相关接口
camera_bp = Blueprint('camera', __name__)   # 摄像头控制相关接口
inspection_bp = Blueprint('inspection', __name__)  # 持久化质检工作流

# 导入路由函数（避免循环引用，必须在蓝图创建后导入）
from app.routes import (
    camera_routes,
    image_routes,
    inspection_routes,
    main_routes,
    video_routes,
)
