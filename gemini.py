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
        prompt = (
            "Проанализируй это изображение-референс. "
            "Сформируй на русском языке готовый промпт для генерации изображения в Nano Banana, "
            "в котором будут отражены СТИЛЬ, ОСВЕЩЕНИЕ, КОМПОЗИЦИЯ и НАСТРОЕНИЕ сцены. "
            "Не описывай внешность конкретного человека. "
            "Ответ верни одной компактной связной формулировкой без списков и заголовков."
        )
        
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
        return "Кинематографичное освещение, фотореалистичный стиль, высокая детализация."

async def generate_final_image(face_bytes: bytes, style_bytes: bytes, user_traits: dict, style_desc: str, user_hints: str, params: dict):
    """Генерирует финальное изображение."""
    client = get_client()

    image_size = "1K" if params.get('quality') == '1K' else "2K"
    aspect_ratio = params.get('ratio', '9:16')
    eyes = user_traits.get('eyes') or "естественные"
    hair_color = user_traits.get('hairColor') or "естественный"
    hair_length = user_traits.get('hairLength') or "естественная"

    prompt_text = f"""
    Сгенерируй фотореалистичное изображение.
    СУБЪЕКТ: человек с первого изображения.
    ГЛАЗА: {eyes}. ВОЛОСЫ: {hair_color}, {hair_length}.
    СТИЛЬ: {style_desc or 'сохранить естественный фотореализм'}.
    ДЕТАЛИ: {user_hints or '-'}.
    """

    if not style_bytes:
        prompt_text = f"""
        Сгенерируй фотореалистичный портрет человека с предоставленного изображения.
        ГЛАЗА: {eyes}. ВОЛОСЫ: {hair_color}, {hair_length}.
        ДЕТАЛИ: {user_hints or '-'}.
        """

    parts = []
    if face_bytes:
        parts.append(types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"))
    
    if style_bytes:
        parts.append(types.Part.from_bytes(data=style_bytes, mime_type="image/jpeg"))
        
    parts.append(types.Part(text=prompt_text))

    # Модель Gemini 3 Pro Image Preview
    response = client.models.generate_content(
        model='gemini-3-pro-image-preview',
        contents=[types.Content(parts=parts)],
        config=types.GenerateContentConfig(
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            )
        )
    )

    # Извлечение картинки
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                raw_data = part.inline_data.data
                # В разных версиях SDK data может быть raw bytes или base64-строкой.
                if isinstance(raw_data, str):
                    image_data = base64.b64decode(raw_data)
                else:
                    image_data = raw_data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                return {
                    "image": image_data,
                    "mime_type": mime_type,
                    "prompt": prompt_text
                }
    
    raise Exception("Model returned no image data.")
