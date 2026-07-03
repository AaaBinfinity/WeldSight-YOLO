import os
import time
import threading
import cv2
from flask import current_app, request, Response, jsonify
from app.routes import camera_bp
from app.camera_handler import camera_loop

@camera_bp.route('/video_feed')
def video_feed():
    """摄像头实时流接口（MJPEG格式）"""
    # 获取当前Flask应用实例（关键：避免依赖current_app在生成器中失效）
    app = current_app._get_current_object()  # 获取原始应用实例，而非代理

    def generate_mjpeg():
        """生成MJPEG流格式数据"""
        # 手动激活应用上下文（核心修复）
        with app.app_context():
            while True:
                # 读取最新帧（此时current_app可用）
                with current_app.camera_vars['latest_frame_lock']:
                    frame_bytes = current_app.camera_vars['latest_frame']
                
                # 无帧时返回占位图
                if frame_bytes is None:
                    placeholder_path = os.path.join(current_app.static_folder, 'placeholder.jpg')
                    if os.path.exists(placeholder_path):
                        placeholder = cv2.imread(placeholder_path)
                        _, jpg = cv2.imencode('.jpg', placeholder)
                        frame_bytes = jpg.tobytes()
                    else:
                        time.sleep(0.05)
                        continue
                
                # 生成MJPEG流格式
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                # time.sleep(0.001)   
    
    return Response(
        generate_mjpeg(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@camera_bp.route('/cam_status')
def cam_status():
    """查询摄像头状态（检测结果、时间戳、错误信息）"""
    with current_app.camera_vars['cam_state_lock']:
        return jsonify(current_app.camera_vars['cam_state'])

@camera_bp.route('/start_cam', methods=['GET', 'POST'])
def start_cam():
    """
    启动摄像头接口
    请求参数：?index=0（摄像头索引，默认0）
    返回：启动状态和当前摄像头索引
    """
    # 检查是否已在运行
    if (current_app.camera_vars['cam_thread'] 
        and current_app.camera_vars['cam_thread'].is_alive()):
        return jsonify({
            "status": "已在运行",
            "cam_index": current_app.camera_vars['cam_index'],
            "success": True
        })
    
    # 获取并验证摄像头索引
    try:
        cam_index = int(request.args.get('index', current_app.config['CAMERA_DEFAULT_INDEX']))
    except ValueError:
        return jsonify({
            "status": "参数错误",
            "error": "摄像头索引必须是整数",
            "success": False
        }), 400
    
    # 预检查摄像头可用性
    temp_cap = cv2.VideoCapture(cam_index)
    if not temp_cap.isOpened():
        temp_cap.release()
        error_msg = f"摄像头 {cam_index} 不可用（未找到或被占用）"
        with current_app.camera_vars['cam_state_lock']:
            current_app.camera_vars['cam_state']['error'] = error_msg
        return jsonify({
            "status": "启动失败",
            "cam_index": cam_index,
            "error": error_msg,
            "success": False
        }), 500
    temp_cap.release()
    
    # 启动摄像头线程
    current_app.camera_vars['stop_cam'] = False
    current_app.camera_vars['cam_index'] = cam_index
    current_app.camera_vars['cam_thread'] = threading.Thread(
        target=camera_loop,
        args=(
            cam_index,
            current_app.camera_vars,
            current_app.model,
            current_app.config['CONF_THRESH']
        ),
        daemon=True
    )
    current_app.camera_vars['cam_thread'].start()
    
    return jsonify({
        "status": "已启动",
        "cam_index": cam_index,
        "success": True
    })

@camera_bp.route('/stop_cam', methods=['GET', 'POST'])
def stop_cam():
    """停止摄像头并释放资源"""
    current_app.camera_vars['stop_cam'] = True  # 设置停止标志
    # 清空最新帧
    with current_app.camera_vars['latest_frame_lock']:
        current_app.camera_vars['latest_frame'] = None
    return jsonify({"status": "已停止", "success": True})