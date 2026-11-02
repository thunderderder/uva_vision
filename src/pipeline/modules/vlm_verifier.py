import re

import torch
from transformers import AutoModelForImageTextToText, AutoProcessor

from qwen_vl_utils import process_vision_info

class VLMVerifier:
    """
    Phase 3: Global Context Verification (Backend)
    Uses Qwen-VL to verify the Visual Prompts using environmental context.
    """
    def __init__(self, model_dir):
        print(f"Loading Qwen-VL model from {model_dir}...")
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_dir, torch_dtype=torch.bfloat16, device_map="auto"
        )
        self.processor = AutoProcessor.from_pretrained(model_dir)

    def verify(self, image_array, classes_to_find, detections, prompt_template, max_new_tokens):
        """
        Takes the visually prompted image and a list of object classes to verify.
        Returns:
            Parsed list of dictionaries containing verified ID, Type, and Description.
        """
        # Convert numpy RGB array back to PIL Image if needed for processor
        from PIL import Image
        pil_image = Image.fromarray(image_array)

        # Construct prompt matching the PRD description
        ids_str = ", ".join([str(d["id"]) for d in detections])
        classes_str = ", ".join(classes_to_find)
        
        prompt = prompt_template.format(ids_str=ids_str, classes_str=classes_str)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.model.device)

        generated_ids = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]
        
        return self._parse_output(output_text)
        
    def _parse_output(self, text):
        """
        Parses Qwen-VL's raw text response into structured data.
        """
        verified_results = []
        description = ""
        
        for line in text.split("\n"):
            line = line.strip()
            # Parse ID and Type
            match = re.match(r"(?i)ID:\s*(\d+),\s*Type:\s*(.+)", line)
            if match:
                obj_id = int(match.group(1))
                obj_type = match.group(2).strip()
                verified_results.append({
                    "id": obj_id,
                    "type": obj_type
                })
            # Parse Description
            elif line.lower().startswith("description:"):
                description = line.split(":", 1)[1].strip()
            elif description and line: # Handle multi-line description
                description += " " + line
                
        return {
            "verified_objects": verified_results,
            "description": description,
            "raw_text": text
        }
