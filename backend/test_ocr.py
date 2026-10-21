
from pathlib import Path
from app.ocr_service import extract_text

file_path = Path(input("Enter full certificate file path: ").strip().strip('"'))

if not file_path.exists():
    print("ERROR: Certificate file not found:", file_path)
else:
    try:
        text = extract_text(file_path.read_bytes(), file_path.name)
        print("\n========== OCR OUTPUT ==========\n")
        print(text if text.strip() else "No text detected.")
        print("\n========== END ==========")
    except Exception as e:
        print("OCR ERROR:", repr(e))
