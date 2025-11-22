import cv2
from ultralytics import YOLO

# 加载模型（替换为你的 best.pt）
model = YOLO("best.pt")

# 输入视频路径
video_path = "input.mp4"
cap = cv2.VideoCapture(video_path)

# 获取视频信息
fps = int(cap.get(cv2.CAP_PROP_FPS))
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# 输出视频保存路径（注意编码器）
out = cv2.VideoWriter("output.mp4", cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # YOLOv8 默认输入是 BGR（OpenCV 读出来就是 BGR），不用手动转 RGB
    results = model(frame, verbose=False)

    # 可视化检测结果
    annotated_frame = results[0].plot()  # 返回 numpy BGR 图像

    # 注意：OpenCV 保存需要 BGR 格式，所以这里直接写 annotated_frame 就行
    out.write(annotated_frame)

    # 如果你想边看边处理，可以加上下面的显示代码
    # cv2.imshow("YOLOv8 Detection", annotated_frame)
    # if cv2.waitKey(1) & 0xFF == ord("q"):
    #     break

cap.release()
out.release()
cv2.destroyAllWindows()
