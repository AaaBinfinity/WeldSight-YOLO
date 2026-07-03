import io
import cv2
import numpy as np
from PIL import Image
from flask import current_app, request, Response, jsonify
from app.routes import image_bp
from app.inference import render_detections

@image_bp.route('/detect_image', methods=['POST'])
def detect_image():
    """
    图片检测接口
    请求：POST 表单，包含 'image' 字段（图片文件）
    返回：带检测框的 JPEG 图片
    """
    # 检查模型是否加载
    if not current_app.model:
        return jsonify({"error": "YOLO模型未加载，无法检测"}), 500
    
    # 检查是否上传图片
    if 'image' not in request.files:
        return jsonify({"error": "未上传图片，请添加 'image' 字段"}), 400
    
    # 读取并转换图片格式（PIL → OpenCV）
    img_file = request.files['image']
    try:
        img_bytes = img_file.read()
        pil_img = Image.open(io.BytesIO(img_bytes)).convert('RGB')  # 统一转为RGB
        frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)   # 转为OpenCV的BGR格式
    except Exception as e:
        return jsonify({"error": f"图片解析失败：{str(e)}"}), 400
    
    # 模型检测与绘制结果
    try:
        detected_frame, _ = render_detections(
            current_app.model,
            frame,
            current_app.config['CONF_THRESH'],
        )
    except Exception as e:
        print(f"图片检测错误：{e}")
        detected_frame = frame  # 失败时返回原图
    
    # 返回JPEG图片
    encoded, jpg_bytes = cv2.imencode('.jpg', detected_frame)
    if not encoded:
        return jsonify({"error": "检测结果编码失败"}), 500
    return Response(jpg_bytes.tobytes(), mimetype='image/jpeg')
