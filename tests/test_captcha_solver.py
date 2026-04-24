import asyncio
import os
import sys

# Ensure app is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_init():
    print("Testing ddddocr initialization...")
    try:
        from app.services.qiandu_search.captcha import captcha_solver
        if captcha_solver._ocr:
            print("Successfully initialized ddddocr OCR engine.")
        else:
            print("ddddocr init returned None (check dependencies).")
    except Exception as e:
        print(f"Failed to load captcha solver: {e}")

if __name__ == "__main__":
    test_init()
