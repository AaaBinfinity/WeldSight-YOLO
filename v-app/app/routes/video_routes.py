import os
import threading
from flask import current_app, request, jsonify, send_from_directory
from app.routes import video_bp
from app.video_processor import process_video_async, sanitize_filename

@video_bp.route('/upload_video', methods=['POST'])
def upload_video():
    """
    视频上传接口
    请求：POST 表单，包含 'video' 字段（视频文件）
    返回：处理后视频的访问URL和文件名
    """
    # 检查模型是否加载
    if not current_app.model:
        return jsonify({
            "error": "YOLO模型未加载，无法处理视频",
            "success": False
        }), 500
    
    # 检查是否上传视频
    if 'video' not in request.files:
        return jsonify({
            "error": "未上传视频，请添加 'video' 字段",
            "success": False
        }), 400
    
    # 处理文件名与路径
    video_file = request.files['video']
    filename = sanitize_filename(video_file.filename)  # 过滤特殊字符
    in_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"in_{filename}")  # 原始视频
    out_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"out_{filename}")  # 处理后视频
    
    # 保存上传的视频
    try:
        video_file.save(in_path)
        print(f"已保存上传视频：{in_path}")
    except Exception as e:
        return jsonify({
            "error": f"视频保存失败：{str(e)}",
            "success": False
        }), 500
    
    # 启动异步处理线程
    threading.Thread(
        target=process_video_async,
        args=(
            filename,
            in_path,
            out_path,
            current_app.video_vars,
            current_app.model,
            current_app.config['CONF_THRESH'],
            current_app.config['VIDEO_MAX_PROGRESS_CACHE']
        ),
        daemon=True
    ).start()
    
    # 返回处理后视频的访问URL
    return jsonify({
        "filename": filename,
        "url": f"/download/out_{filename}",
        "success": True
    })

@video_bp.route('/video_progress')
def video_progress():
    """
    视频处理进度查询接口
    请求参数：?filename=xxx（上传时返回的文件名）
    返回：进度百分比（0-100）和状态（waiting/processing/completed/failed）
    """
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"progress": 0, "status": "waiting"})
    
    # 获取当前进度
    with current_app.video_vars['progress_lock']:
        progress = current_app.video_vars['video_progress'].get(filename, 0)
    
    # 解析状态
    if progress == -1:
        status = "failed"
    elif progress == 0:
        status = "waiting"
    elif 0 < progress < 100:
        status = "processing"
    else:
        status = "completed"
    
    return jsonify({"progress": progress, "status": status})

@video_bp.route('/download/<path:filename>')
def download_video(filename):
    """
    视频下载接口（仅允许下载处理后的视频）
    安全控制：仅允许下载 out_ 前缀的文件，防止路径穿越
    """
    # 安全校验：仅允许下载处理后的视频
    if not filename.startswith('out_'):
        return jsonify({"error": "仅允许下载处理后的视频"}), 403
    
    # 验证文件存在性
    safe_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(safe_path) or not os.path.isfile(safe_path):
        return jsonify({"error": "视频文件不存在或已过期"}), 404
    
    # 流式返回视频（支持在线播放）
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=False,  # 允许在线播放（设为True则强制下载）
        mimetype='video/x-msvideo'  # AVI格式MIME类型
    )