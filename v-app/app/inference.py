"""Shared helpers for running YOLO inference on OpenCV frames."""


def run_detections(model, frame, conf_thresh, image_size=640):
    """Return the annotated frame and serializable YOLO detection details."""
    if model is None:
        return frame, []

    results = model(frame, conf=conf_thresh, imgsz=image_size)
    result = results[0] if results else None
    if result is None:
        return frame, []

    names = getattr(result, 'names', {}) or {}
    detections = []
    boxes = getattr(result, 'boxes', None)
    if boxes is not None:
        for box in boxes:
            class_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            coordinates = [round(float(value), 2) for value in box.xyxy[0].tolist()]
            detections.append({
                'class_id': class_id,
                'class_name': str(names.get(class_id, class_id)),
                'confidence': round(confidence, 4),
                'box_xyxy': coordinates,
            })

    return result.plot(), detections


def render_detections(model, frame, conf_thresh, image_size=640):
    """Backward-compatible helper returning annotated frame and detection flag."""
    rendered, detections = run_detections(model, frame, conf_thresh, image_size)
    return rendered, bool(detections)
