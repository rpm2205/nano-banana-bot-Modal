import os
import base64
from google import genai
from google.genai import types

def get_client():
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not found in environment variables")
    return genai.Client(api_key=api_key)

async def analyze_style(image_bytes: bytes) -> str:
    """Анализирует стиль изображения для создания промпта."""
    try:
        client = get_client()
        prompt = "Analyze this image. Describe the ART STYLE, LIGHTING, COMPOSITION, and MOOD in a concise, descriptive paragraph. Do NOT describe the specific person."
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        types.Part(text=prompt),
                    ]
                )
            ]
        )
        return response.text
    except Exception as e:
        print(f"Style Analysis Error: {e}")
        return "Cinematic lighting, high quality, photorealistic style."

async def generate_final_image(face_bytes: bytes, style_bytes: bytes, user_traits: dict, style_desc: str, user_hints: str, params: dict):
    """Генерирует финальное изображение."""
    client = get_client()

    prompt_text = f"""
    Generate a photorealistic image.
    SUBJECT: Person from First Image.
    EYES: {user_traits.get('eyes', 'default')}. HAIR: {user_traits.get('hairColor', 'default')}, {user_traits.get('hairLength', 'default')}.
    STYLE: {style_desc}.
    DETAILS: {user_hints or '-'}.
    High quality, 8k.
    """

    if not style_bytes:
        prompt_text = f"""
        Photorealistic portrait of person from provided image.
        EYES: {user_traits.get('eyes', 'default')}. HAIR: {user_traits.get('hairColor', 'default')}, {user_traits.get('hairLength', 'default')}.
        DETAILS: {user_hints or '-'}.
        High quality.
        """

    parts = []
    if face_bytes:
        parts.append(types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"))
    
    if style_bytes:
        parts.append(types.Part.from_bytes(data=style_bytes, mime_type="image/jpeg"))
        
    parts.append(types.Part(text=prompt_text))

    # Конфигурация размера
    # В Python SDK конфиг передается немного иначе, используем types
    image_size = "1K" if params.get('quality') == '1K' else "2K"
    aspect_ratio = params.get('ratio', '9:16')
    
    # Модель Gemini 3 Pro Image Preview
    response = client.models.generate_content(
        model='gemini-3-pro-image-preview',
        contents=[types.Content(parts=parts)],
        config=types.GenerateContentConfig(
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size
            )
        )
    )

    # Извлечение картинки
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                # Декодируем base64 обратно в байты
                image_data = base64.b64decode(part.inline_data.data)
                return {
                    "image": image_data,
                    "prompt": prompt_text
                }
    
    raise Exception("Model returned no image data.")
