import google.generativeai as genai
from PIL import Image
import io
import time

def gemini_ocr_image(image: Image.Image, api_key: str) -> str:
    """
    Use Gemini 2.5 Pro model to perform OCR on a PIL Image, with up to 3 retries if no text is returned.
    Args:
        image: PIL Image object (single page)
        api_key: Google Gemini API key
    Returns:
        Extracted text as string
    """
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name='gemini-1.5-pro')
    prompt_text = "You are an expert OCR system. Extract all readable text from this scanned document image. Return only the text, preserving line breaks."
    if image.mode != "RGB":
        image = image.convert("RGB")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    img_bytes = buf.getvalue()
    request_contents = [
                prompt_text,
                {"mime_type": "image/png", "data": img_bytes}
            ]
    for attempt in range(5):
        try:
            response = model.generate_content(
                request_contents,
                generation_config={"temperature": 0},
                stream=False
            )
            if hasattr(response, 'text') and response.text:
                return response.text
            else:
                print(f"[Gemini DEBUG] No text returned, attempt {attempt+1}/5. Retrying...")
        except Exception as e:
            print(f"[Gemini DEBUG] Exception on attempt {attempt+1}/5:", e)
            # if 'response' in locals():
            #     print("[Gemini DEBUG] Raw response object:", response)
        time.sleep(10)  # brief pause before retry
    return "[Gemini OCR Error]: No text extracted after 5 attempts."
