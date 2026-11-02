import cv2
import numpy as np


def box_label(det: dict) -> str:
    det_id = det.get("id", "?")
    yolo = det.get("yolo_confidence")
    if yolo is not None:
        try:
            return f"[{det_id}] {float(yolo):.3f}"
        except (TypeError, ValueError):
            pass
    conf = det.get("confidence")
    if isinstance(conf, (int, float)):
        return f"[{det_id}] {float(conf):.3f}"
    return f"[{det_id}]"


class VisualPrompter:
    """
    Phase 2: Visual Prompting
    Draws red boxes and ID labels directly on the full 1024x1024 slice.
    This allows the VLM to see the complete environmental context.
    """
    def __init__(self, color=(255, 0, 0), thickness=3, font_scale=1.5):
        # RGB color for OpenCV
        self.color = color
        self.thickness = thickness
        self.font_scale = font_scale
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def inject_prompt(self, image, detections, bbox_key="bbox"):
        """
        Injects visual prompts (red bounding boxes and IDs) onto the image.
        Returns:
            The annotated image array (numpy)
        """
        # Create a copy so we don't modify the original array inplace
        annotated_img = np.copy(image)
        
        for det in detections:
            x1, y1, x2, y2 = det[bbox_key]
            det_id = det["id"]
            
            # Draw red bounding box
            cv2.rectangle(annotated_img, (x1, y1), (x2, y2), self.color, self.thickness)
            
            # Draw label: [id] + confidence when available (YOLO conf)
            label = box_label(det)
            
            # Add a filled background for the text to make it legible
            (text_width, text_height), baseline = cv2.getTextSize(label, self.font, self.font_scale, self.thickness)
            cv2.rectangle(annotated_img, (x1, max(0, y1 - text_height - baseline)), (x1 + text_width, y1), self.color, cv2.FILLED)
            
            # Put white text on the red background
            cv2.putText(annotated_img, label, (x1, y1 - baseline), self.font, self.font_scale, (255, 255, 255), self.thickness)
            
        return annotated_img
