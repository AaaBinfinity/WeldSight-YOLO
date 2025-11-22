import cv2
import numpy as np
from ultralytics import YOLO
from PIL import ImageGrab  # 用于截取屏幕

# 加载训练好的 YOLOv8 模型
model = YOLO("best.pt")

while True:
    # 截取全屏
    frame = np.array(ImageGrab.grab())  # 已经是 RGB

    # 使用模型进行预测
    results = model(frame)

    # 可视化检测结果
    annotated_frame = results[0].plot()

    # 转回 BGR 显示（OpenCV 需要 BGR）
    annotated_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)

    cv2.imshow("YOLOv8 Screen Detection", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
