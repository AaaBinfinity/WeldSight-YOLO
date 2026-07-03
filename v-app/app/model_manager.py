from ultralytics import YOLO

def load_yolo_model(model_path):
    """
    加载YOLO模型
    :param model_path: 模型文件路径（.pt）
    :return: 加载成功的YOLO模型实例，失败则返回None
    """
    try:
        model = YOLO(model_path)
        print(f"✅ 成功加载YOLO模型: {model_path}")
        return model
    except Exception as e:
        print(f"❌ YOLO模型加载失败 | 错误信息: {str(e)}")
        return None