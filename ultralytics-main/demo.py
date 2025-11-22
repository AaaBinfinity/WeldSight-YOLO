from ultralytics import YOLO
model = YOLO('yolo11n.pt')  # 使用更大的模型
model.train(data='data.yaml', workers=0, epochs=100, batch=32, imgsz=640)
