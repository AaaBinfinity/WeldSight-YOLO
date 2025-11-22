import cv2
from ultralytics import YOLO

# 加载训练好的 YOLOv8 模型
model = YOLO("best.pt")  # 请确保 best.pt 在当前目录或给出完整路径

# 打开默认摄像头 (0)
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("无法打开摄像头")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("无法读取摄像头帧")
        break

    # OpenCV 默认是 BGR，YOLOv8 模型使用 RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 使用模型进行预测
    results = model(rgb_frame)

    # 可视化检测结果
    annotated_frame = results[0].plot()

    # 转回 BGR 显示
    annotated_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)

    # 显示结果
    cv2.imshow("YOLOv8 Camera Detection", annotated_frame)

    # 按 'q' 键退出
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
