import os
import time
import threading
import cv2
from flask import current_app

def init_video_global_vars():
    """初始化视频处理相关全局变量"""
    return {
        'video_progress': {},  # 视频处理进度：{文件名: 进度百分比（-1=失败）}
        'progress_lock': threading.Lock()  # 进度锁
    }

def process_video_async(filename, in_path, out_path, video_vars, model, conf_thresh, cache_time):
    """
    异步处理视频：读取→检测→生成带框视频（XVID编码，无外部依赖）
    :param filename: 原始文件名（用于进度标识）
    :param in_path: 输入视频路径
    :param out_path: 输出视频路径
    :param video_vars: 视频全局变量字典
    :param model: YOLO模型实例
    :param conf_thresh: 检测置信度阈值
    :param cache_time: 进度缓存时间（秒）
    """
    # 打开输入视频
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        print(f"❌ 无法打开输入视频: {in_path}")
        with video_vars['progress_lock']:
            video_vars['video_progress'][filename] = -1  # 标记失败
        return

    # 获取视频基础参数（XVID编码要求宽高为偶数）
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0  # 默认25fps
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # 调整宽高为偶数（XVID编码强制要求）
    frame_width += frame_width % 2
    frame_height += frame_height % 2
    total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))  # 避免总帧数为0

    # 初始化视频写入器（XVID编码+AVI格式，兼容性强）
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out_vid = cv2.VideoWriter(out_path, fourcc, fps, (frame_width, frame_height))

    # 初始化进度
    with video_vars['progress_lock']:
        video_vars['video_progress'][filename] = 0

    try:
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break  # 视频读取完毕

            # 模型检测与帧绘制
            if model:
                results = model(frame, conf=conf_thresh, imgsz=640)
                r = results[0]
                rendered_frame = r.plot()  # 绘制检测框
            else:
                rendered_frame = frame  # 无模型时返回原图

            # 写入输出视频
            out_vid.write(rendered_frame)

            # 更新进度（避免超过100%）
            frame_idx += 1
            progress = min(100, int((frame_idx / total_frames) * 100))
            with video_vars['progress_lock']:
                video_vars['video_progress'][filename] = progress

            time.sleep(0.001)  # 降低CPU占用

        # 处理完成，标记100%
        with video_vars['progress_lock']:
            video_vars['video_progress'][filename] = 100
        print(f"✅ 视频处理完成: {filename} | 输出路径: {out_path}")

    except Exception as e:
        print(f"❌ 视频处理错误 {filename}: {str(e)}")
        with video_vars['progress_lock']:
            video_vars['video_progress'][filename] = -1  # 标记失败

    finally:
        # 释放资源
        cap.release()
        out_vid.release()
        # 定时清理进度缓存（避免内存泄漏）
        threading.Timer(
            cache_time,
            lambda: video_vars['video_progress'].pop(filename, None)
        ).start()

def sanitize_filename(filename):
    """
    清理文件名（过滤特殊字符，避免路径穿越攻击）
    :param filename: 原始文件名
    :return: 安全的文件名
    """
    if not filename:
        return f"upload_{int(time.time())}.avi"  # 默认文件名
    # 只保留字母、数字、点、下划线
    return "".join([c for c in filename if c.isalnum() or c in ['.', '_']])