"""Shared helpers for running YOLO inference on OpenCV frames."""


def render_detections(model, frame, conf_thresh, image_size=640):
    """Return the annotated frame and whether any object was detected."""
    if model is None:
        return frame, False

    results = model(frame, conf=conf_thresh, imgsz=image_size)
    result = results[0] if results else None
    if result is None:
        return frame, False

    return result.plot(), len(result.boxes) > 0
