import threading
import time
import cv2
from flask import current_app

# 修改：增加 default_cam_index 参数，接收外部传入的默认索引
def init_camera_global_vars(default_cam_index):
    """初始化摄像头相关全局变量（通过参数接收配置，避免依赖current_app）"""
    return {
        'latest_frame': None,          # 最新帧数据（JPEG字节流）
        'latest_frame_lock': threading.Lock(),  # 帧数据锁
        'stop_cam': True,              # 摄像头停止标志
        'cam_thread': None,            # 摄像头线程实例
        'cam_index': default_cam_index,  # ✅ 从参数获取默认索引，不再依赖current_app
        'cam_state': {                 # 摄像头状态（检测结果、时间戳、错误）
            'last_detected': False,
            'last_ts': 0,
            'error': None
        },
        'cam_state_lock': threading.Lock()  # 状态锁
    }
 

def camera_loop(cam_index, camera_vars, model, conf_thresh):
    """
    摄像头循环：读取帧→模型检测→更新最新帧
    :param cam_index: 摄像头索引
    :param camera_vars: 摄像头全局变量字典
    :param model: YOLO模型实例
    :param conf_thresh: 检测置信度阈值
    """
    # 打开摄像头
    cap = cv2.VideoCapture(int(cam_index))
    if not cap.isOpened():
        error_msg = f"摄像头 {cam_index} 无法打开（可能被占用或不存在）"
        print(f"❌ {error_msg}")
        with camera_vars['cam_state_lock']:
            camera_vars['cam_state']['error'] = error_msg
        return

    # 清除错误状态
    with camera_vars['cam_state_lock']:
        camera_vars['cam_state']['error'] = None

    # 循环读取并处理帧
    while not camera_vars['stop_cam']:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)  # 无帧时短暂休眠，降低CPU占用
            continue

        # 模型检测（异常捕获）
        try:
            if model:
                results = model(frame, conf=conf_thresh, imgsz=640)
                r = results[0] if results else None
                rendered_frame = r.plot() if r else frame  # 绘制检测框
                detected = len(r.boxes) > 0 if r else False
            else:
                rendered_frame = frame
                detected = False
        except Exception as e:
            print(f"❌ 摄像头检测错误: {str(e)}")
            rendered_frame = frame
            detected = False

        # 更新最新帧（JPEG格式，减少传输体积）
        _, jpg_bytes = cv2.imencode('.jpg', rendered_frame)
        with camera_vars['latest_frame_lock']:
            camera_vars['latest_frame'] = jpg_bytes.tobytes()

        # 更新摄像头状态
        with camera_vars['cam_state_lock']:
            camera_vars['cam_state']['last_detected'] = detected
            camera_vars['cam_state']['last_ts'] = time.time()

        time.sleep(0.01)  

    # 释放资源
    cap.release()
    with camera_vars['latest_frame_lock']:
        camera_vars['latest_frame'] = None  # 清空帧数据
    print(f"ℹ️  摄像头 {cam_index} 已停止并释放资源")