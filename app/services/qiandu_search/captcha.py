import base64
import logging
from typing import Optional, Tuple

try:
    import ddddocr
except ImportError:
    ddddocr = None

logger = logging.getLogger(__name__)

class QianduCaptchaSolver:
    """Utility to solve captchas using ddddocr."""

    def __init__(self):
        self._ocr = None
        if ddddocr:
            # We initialize OCR on demand to save memory if not used
            # show_ad=False is important for clean logs
            try:
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                self._det = ddddocr.DdddOcr(det=True, show_ad=False)
            except Exception as e:
                logger.error(f"Failed to initialize ddddocr: {e}")

    def find_slider_offset(self, target_bytes: bytes, background_bytes: bytes) -> Optional[int]:
        """
        Find the x-offset of a slider gap.
        :param target_bytes: The small slider piece image bytes.
        :param background_bytes: The background image bytes with the gap.
        :return: Integer x-offset or None.
        """
        if not self._ocr:
            logger.warning("ddddocr not available, skipping slider detection.")
            return None

        try:
            res = self._ocr.slide_match(target_bytes, background_bytes, simple_target=True)
            # res is usually a dict like {"target": [x1, y1, x2, y2]}
            if res and "target" in res:
                return res["target"][0] # Return the x1 coordinate
        except Exception as e:
            logger.error(f"Error during slider matching: {e}")
        
        return None

    def recognize_text(self, image_bytes: bytes) -> str:
        """Recognize alphanumeric characters from an image."""
        if not self._ocr:
            return ""
        try:
            return self._ocr.classification(image_bytes)
        except Exception as e:
            logger.error(f"Error during text recognition: {e}")
            return ""

# Singleton instance
captcha_solver = QianduCaptchaSolver()
