from flask import current_app, jsonify
from app.routes import main_bp

@main_bp.route('/')
def index():
    """首页：返回静态HTML页面"""
    return current_app.send_static_file('index.html')

@main_bp.route('/service_status')
def service_status():
    """查询服务整体状态（模型、摄像头、任务数）"""
    # 模型状态
    model_status = "已加载" if current_app.model else "未加载"
    
    # 摄像头状态
    with current_app.camera_vars['cam_state_lock']:
        cam_error = current_app.camera_vars['cam_state'].get('error')
        cam_running = (current_app.camera_vars['cam_thread'] 
                      and current_app.camera_vars['cam_thread'].is_alive())
    
    # 视频处理任务数
    with current_app.video_vars['progress_lock']:
        video_task_count = len(current_app.video_vars['video_progress'])
    
    return jsonify({
        "service_status": "正常运行",
        "model_status": model_status,
        "camera_status": "运行中" if cam_running else "已停止",
        "camera_error": cam_error,
        "video_task_count": video_task_count
    })