import cv2
import numpy as np

class ImageSlicer:
    """
    Phase 1a: High-Res Image Slicing (Frontend)
    Slices a 4K image into 1024x1024 patches to preserve small object details.
    """
    def __init__(self, slice_size=1024, overlap_ratio=0.2):
        self.slice_size = slice_size
        self.overlap = int(slice_size * overlap_ratio)
        self.stride = self.slice_size - self.overlap

    def slice_image(self, image_path):
        """
        Reads an image and slices it into overlapping patches.
        Returns:
            list of dicts containing 'image', 'x_offset', 'y_offset'
        """
        img = cv2.imread(image_path)
        if img is None:
            raise FileNotFoundError(f"Could not read image: {image_path}")
        
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return self._slice_rgb_array(img)

    def slice_rgb(self, img_rgb):
        """
        与 slice_image 相同切片逻辑，输入为 RGB numpy (H,W,3)。
        """
        if img_rgb is None or img_rgb.ndim != 3 or img_rgb.shape[2] != 3:
            raise ValueError("img_rgb must be HxWx3 RGB")
        return self._slice_rgb_array(img_rgb)

    def _slice_rgb_array(self, img):
        h, w, _ = img.shape

        slices = []
        for y in range(0, h, self.stride):
            for x in range(0, w, self.stride):
                y1, y2 = y, min(y + self.slice_size, h)
                x1, x2 = x, min(x + self.slice_size, w)

                if y2 - y1 < self.slice_size:
                    y1 = max(0, y2 - self.slice_size)
                if x2 - x1 < self.slice_size:
                    x1 = max(0, x2 - self.slice_size)

                slice_img = img[y1:y2, x1:x2]
                slices.append(
                    {
                        "image": slice_img,
                        "x_offset": x1,
                        "y_offset": y1,
                    }
                )

        return slices
