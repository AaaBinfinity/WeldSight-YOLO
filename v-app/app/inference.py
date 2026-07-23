"""Shared helpers for running YOLO inference on OpenCV frames."""

from app.defect_classes import defect_label


def run_detections(model, frame, conf_thresh, image_size=640):
    """Return the annotated frame and serializable YOLO detection details."""
    if model is None:
        return frame, []

    results = model(frame, conf=conf_thresh, imgsz=image_size)
    result = results[0] if results else None
    if result is None:
        return frame, []

    names = getattr(result, 'names', {}) or {}
    canonical_names = {
        class_id: defect_label(class_id, name)
        for class_id, name in names.items()
    }
    result.names = canonical_names
    detections = []
    boxes = getattr(result, 'boxes', None)
    if boxes is not None:
        for box in boxes:
            class_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            coordinates = [round(float(value), 2) for value in box.xyxy[0].tolist()]
            detections.append({
                'class_id': class_id,
                'class_name': canonical_names.get(
                    class_id,
                    defect_label(class_id, names.get(class_id)),
                ),
                'confidence': round(confidence, 4),
                'box_xyxy': coordinates,
            })

    return result.plot(), detections


def render_detections(model, frame, conf_thresh, image_size=640):
    """Backward-compatible helper returning annotated frame and detection flag."""
    rendered, detections = run_detections(model, frame, conf_thresh, image_size)
    return rendered, bool(detections)
