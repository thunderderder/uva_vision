import json

class Postprocessor:
    """
    Phase 4: Postprocessing Integration
    Merges YOLO-World detections and Qwen-VL verifications into a final structured JSON.
    """
    def __init__(self, target_classes):
        self.target_classes = [cls.lower() for cls in target_classes]

    def process(self, original_detections, vlm_results):
        """
        Merge results into final JSON structure.
        Returns:
            A JSON-serializable list of alarm objects and scene description.
        """
        final_results = []
        verified_map = {obj['id']: obj['type'] for obj in vlm_results.get('verified_objects', [])}
        
        for det in original_detections:
            det_id = det["id"]
            yolo_class = det["class_name"]
            vlm_type = verified_map.get(det_id, "unknown")
            bbox_out = det.get("global_bbox", det["bbox"])
            bbox_out = [int(round(float(x))) for x in bbox_out]
            
            # If Qwen-VL identified it as one of our target classes or confirmed it's garbage
            is_target = any(t in vlm_type.lower() for t in self.target_classes)
            
            # Additional check: if VLM says it's normal/background, it's not a target
            if "normal" in vlm_type.lower() or "unknown" in vlm_type.lower():
                is_target = False
                
            status = "confirmed_alarm" if is_target else "false_alarm"
            
            alarm = {
                "id": det_id,
                "type": vlm_type,
                "yolo_raw_class": yolo_class,
                "confidence": "high" if is_target else "low",
                "status": status,
                "bbox": bbox_out,
                "global_bbox": bbox_out,
            }
            yc = det.get("confidence")
            if isinstance(yc, (int, float)):
                alarm["yolo_confidence"] = float(yc)
            final_results.append(alarm)
            
        output = {
            "alarms": final_results,
            "scene_description": vlm_results.get("description", ""),
            "raw_vlm_text": vlm_results.get("raw_text", "")
        }
        return output

    def save_json(self, output_dict, save_path):
        """
        Saves the structured dictionary to a JSON file.
        """
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(output_dict, f, ensure_ascii=False, indent=4)
        print(f"Saved post-processed JSON to {save_path}")
