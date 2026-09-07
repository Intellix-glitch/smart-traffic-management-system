import cv2
import os
import time
import torch
from ultralytics import YOLO

# COCO class IDs for vehicles
VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck"
}


def classify_density(count: int) -> str:

    """
    Map a vehicle count to a traffic-density level
    (shared by the detector and the analytics endpoint)
    """

    if count < 10:

        return "LOW"

    if count < 30:

        return "MEDIUM"

    return "HIGH"


class VehicleDetector:

    def __init__(self, model_path="models/yolov8n.pt"):
        """
        Initialize YOLOv8 detector
        Automatically downloads model if not found
        """

        # Load model safely
        self.model = YOLO(
            model_path if os.path.exists(model_path)
            else "yolov8n.pt"
        )

        # GPU support
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)

        print(f"[INFO] YOLOv8 running on: {self.device}")

        # Vehicle class IDs
        self.vehicle_class_ids = list(VEHICLE_CLASSES.keys())

    def detect(self, frame):
        """
        Detect vehicles in a frame

        Returns:
            annotated_frame
            vehicle_count
            detections
        """

        start_time = time.time()

        # Run YOLOv8 inference
        results = self.model(
            frame,
            classes=self.vehicle_class_ids,
            conf=0.4,
            verbose=False
        )[0]

        detections = []
        annotated = frame.copy()

        # Process detections
        for box in results.boxes:

            cls_id = int(box.cls[0])
            conf = float(box.conf[0])

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0]
            )

            label = VEHICLE_CLASSES.get(
                cls_id,
                "vehicle"
            )

            detections.append({
                "class_id": cls_id,
                "class_name": label,
                "confidence": round(conf, 2),
                "bbox": (x1, y1, x2, y2)
            })

            # Draw bounding box
            cv2.rectangle(
                annotated,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            # Draw label
            cv2.putText(
                annotated,
                f"{label} {conf:.0%}",
                (x1, y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )

        # Vehicle count
        count = len(detections)

        # Traffic density analysis
        density = classify_density(count)

        # FPS calculation
        fps = 1 / (time.time() - start_time)

        # Display vehicle count
        cv2.putText(
            annotated,
            f"Vehicles: {count}",
            (10, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 255),
            2
        )

        # Display traffic density
        cv2.putText(
            annotated,
            f"Traffic: {density}",
            (10, 75),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2
        )

        # Display FPS
        cv2.putText(
            annotated,
            f"FPS: {fps:.1f}",
            (10, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2
        )

        return annotated, count, detections

    def detect_from_image_path(self, path):
        """
        Detect vehicles from image path
        """

        frame = cv2.imread(path)

        if frame is None:
            raise FileNotFoundError(
                f"Cannot read image: {path}"
            )

        return self.detect(frame)

    def process_video(
        self,
        source,
        output_path=None,
        callback=None
    ):
        """
        Process video or live stream
        """

        cap = cv2.VideoCapture(source)

        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open video source: {source}"
            )

        writer = None

        # Save output video if path provided
        if output_path:

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            fps = cap.get(cv2.CAP_PROP_FPS)

            if fps == 0:
                fps = 25

            writer = cv2.VideoWriter(
                output_path,
                fourcc,
                fps,
                (w, h)
            )

        try:

            while True:

                ret, frame = cap.read()

                if not ret:
                    break

                annotated, count, detections = self.detect(frame)

                # Save frame
                if writer:
                    writer.write(annotated)

                # Callback support
                if callback:
                    callback(
                        annotated,
                        count,
                        detections
                    )

                # Display live window
                cv2.imshow(
                    "Smart Traffic Detection",
                    annotated
                )

                # Exit key
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

        finally:

            cap.release()

            if writer:
                writer.release()

            cv2.destroyAllWindows()