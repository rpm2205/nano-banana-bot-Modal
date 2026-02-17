import os
import base64
import json
import asyncio
from google import genai
from google.genai import types

FACE_LOCK_RULE = "ВАЖНО: не изменяй внешность человека, черты лица и узнаваемые индивидуальные особенности."

def _truncate_text(value: str, limit: int = 240) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"

def _bytes_signature(data: bytes) -> str:
    if not data:
        return "none"
    head = data[:12]
    return head.hex()

def _guess_mime_by_magic(data: bytes) -> str:
    if not data:
        return "unknown"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "image/heic_or_avif"
    return "unknown"

def _print_genai_call_log(tag: str, payload: dict) -> None:
    try:
        print(f"{tag}: {json.dumps(payload, ensure_ascii=False)}")
    except Exception:
        print(f"{tag}: {payload}")

def _normalize_user_prompt_text(value: str) -> str:
    if not value:
        return ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if lines and lines[0].lower() == "промпт:":
        lines = lines[1:]
    return "\n".join(lines).strip()

def _looks_like_structured_prompt(value: str) -> bool:
    text = (value or "").lower()
    markers = ("сгенерируй", "глаза:", "волосы:", "стиль:", "детали:", "дополнения:", "важно:")
    return any(marker in text for marker in markers)

def _ensure_face_lock_rule(prompt_text: str) -> str:
    text = _normalize_user_prompt_text(prompt_text)
    if not text:
        return text
    if FACE_LOCK_RULE.lower() in text.lower():
        return text
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return FACE_LOCK_RULE
    if len(lines) == 1:
        return f"{lines[0]}\n{FACE_LOCK_RULE}"
    return "\n".join([lines[0], FACE_LOCK_RULE, *lines[1:]])


def _is_transient_genai_error(exc: Exception) -> bool:
    """
    Эвристика для определения «временных» ошибок GenAI,
    которые имеет смысл повторить (например, 500 INTERNAL).
    """
    text = str(exc)
    if "INTERNAL" in text or "'code': 500" in text or '"code": 500' in text:
        return True
    # При необходимости сюда можно добавить другие маркеры.
    return False

def get_client():
    """Получает клиент для модели Pro (gemini-3-pro-image-preview)."""
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not found in environment variables")
    return genai.Client(api_key=api_key)

def get_flash_client():
    """Получает клиент для модели Flash (gemini-2.5-flash)."""
    #API_KEY платный, GEMINI_FLASH_API_KEY бесплатный, но с лимитом 20 запросов в день
    
    #api_key = os.environ.get("GEMINI_FLASH_API_KEY")#бесплатный
    api_key = os.environ.get("API_KEY")#платный
    if not api_key:
        #raise ValueError("GEMINI_FLASH_API_KEY not found in environment variables")
        raise ValueError("API_KEY not found in environment variables")
    return genai.Client(api_key=api_key)

async def analyze_style(image_bytes: bytes) -> str:
    """Анализирует стиль изображения для создания промпта."""
    try:
        client = get_flash_client()
        prompt = (
            "Проанализируй это изображение-референс. "
            "Сформируй на русском языке готовый промпт для генерации изображения в Nano Banana, "
            "в котором будут отражены СТИЛЬ, ОСВЕЩЕНИЕ, КОМПОЗИЦИЯ и НАСТРОЕНИЕ сцены. "
            "Не описывай внешность конкретного человека. "
            "Ответ верни одной компактной связной формулировкой без списков и заголовков."
        )

        _print_genai_call_log(
            "GenAI request analyze_style",
            {
                "model": "gemini-2.5-flash",
                "image_bytes_len": len(image_bytes) if image_bytes else 0,
                "image_magic_mime_guess": _guess_mime_by_magic(image_bytes),
                "image_head_hex": _bytes_signature(image_bytes),
                "prompt_preview": _truncate_text(prompt, 300),
            }
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

async def generate_final_image(face_bytes: bytes, style_bytes: bytes | None, user_traits: dict, style_desc: str, user_hints: str, params: dict):
    """Генерирует финальное изображение."""
    client = get_client()

    image_size = "1K" if params.get('quality') == '1K' else "2K"
    aspect_ratio = params.get('ratio', '9:16')
    eyes = user_traits.get('eyes') or "естественные"
    hair_color = user_traits.get('hairColor') or "естественный"
    hair_length = user_traits.get('hairLength') or "естественная"
    normalized_hints = _normalize_user_prompt_text(user_hints or "")
    use_hints_as_prompt = _looks_like_structured_prompt(normalized_hints)
    has_style_description = bool((style_desc or "").strip())

    if use_hints_as_prompt:
        prompt_text = _ensure_face_lock_rule(normalized_hints)
    elif has_style_description:
        prompt_text = f"""
        Сгенерируй фотореалистичное изображение.
        СУБЪЕКТ: человек с первого изображения.
        {FACE_LOCK_RULE}
        ГЛАЗА: {eyes}. ВОЛОСЫ: {hair_color}, {hair_length}.
        СТИЛЬ: {style_desc or 'сохранить естественный фотореализм'}.
        ДОПОЛНЕНИЯ: {normalized_hints or '-'}.
        """
    else:
        prompt_text = f"""
        Сгенерируй фотореалистичный портрет человека с предоставленного изображения.
        {FACE_LOCK_RULE}
        ГЛАЗА: {eyes}. ВОЛОСЫ: {hair_color}, {hair_length}.
        ДОПОЛНЕНИЯ: {normalized_hints or '-'}.
        """

    parts = []
    if face_bytes:
        parts.append(types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"))
    
    if style_bytes:
        parts.append(types.Part.from_bytes(data=style_bytes, mime_type="image/jpeg"))
        
    parts.append(types.Part(text=prompt_text))

    _print_genai_call_log(
        "GenAI request generate_final_image",
        {
            "model": "gemini-3-pro-image-preview",
            "config": {
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            },
            "params": params or {},
            "user_traits": user_traits or {},
            "has_style_image": bool(style_bytes),
            "face_bytes_len": len(face_bytes) if face_bytes else 0,
            "face_magic_mime_guess": _guess_mime_by_magic(face_bytes),
            "face_head_hex": _bytes_signature(face_bytes),
            "style_bytes_len": len(style_bytes) if style_bytes else 0,
            "style_magic_mime_guess": _guess_mime_by_magic(style_bytes) if style_bytes else "none",
            "style_head_hex": _bytes_signature(style_bytes) if style_bytes else "none",
            "style_desc_preview": _truncate_text(style_desc or "", 300),
            "user_hints_preview": _truncate_text(user_hints or "", 300),
            "prompt_preview": _truncate_text(prompt_text, 500),
        }
    )

    # Модель Gemini 3 Pro Image Preview.
    # Добавляем простейший ретрай для временных внутренних ошибок (например, 500 INTERNAL),
    # чтобы пользователь с большей вероятностью получал результат в рамках одного сценария.
    last_error: Exception | None = None
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
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
            # Если вызов успешный — выходим из цикла и разбираем ответ ниже.
            break
        except Exception as e:
            last_error = e
            if not _is_transient_genai_error(e) or attempt == max_attempts:
                # Нетрaнзитная ошибка или исчерпали попытки — пробрасываем дальше.
                raise
            delay = 1.5 * attempt
            print(
                f"GenAI transient error on generate_final_image, "
                f"attempt={attempt}/{max_attempts}, retry_in={delay:.2f}s, error={e}"
            )
            await asyncio.sleep(delay)
    else:
        # Теоретически недостижимо, но на всякий случай.
        if last_error:
            raise last_error
        raise Exception("Unknown error in generate_final_image retry loop")

    # Извлечение картинки из любого candidate/part.
    candidates = response.candidates or []
    diagnostics = {
        "model": "gemini-3-pro-image-preview",
        "candidate_count": len(candidates),
        "text_preview": _truncate_text(getattr(response, "text", "")),
        "candidates": [],
    }

    for ci, candidate in enumerate(candidates):
        content = getattr(candidate, "content", None)
        candidate_parts = getattr(content, "parts", None) or []
        candidate_log = {
            "index": ci,
            "finish_reason": str(getattr(candidate, "finish_reason", "")),
            "safety_ratings": str(getattr(candidate, "safety_ratings", "")),
            "part_count": len(candidate_parts),
            "parts": [],
        }

        for pi, part in enumerate(candidate_parts):
            inline_data = getattr(part, "inline_data", None)
            inline_mime = getattr(inline_data, "mime_type", None) if inline_data else None
            raw_data = getattr(inline_data, "data", None) if inline_data else None

            candidate_log["parts"].append(
                {
                    "index": pi,
                    "has_inline_data": bool(inline_data),
                    "inline_mime": inline_mime,
                    "inline_data_type": type(raw_data).__name__ if raw_data is not None else None,
                    "inline_data_len": len(raw_data) if hasattr(raw_data, "__len__") else None,
                    "text_preview": _truncate_text(getattr(part, "text", "")),
                }
            )

            if inline_data and raw_data:
                # В разных версиях SDK data может быть raw bytes или base64-строкой.
                if isinstance(raw_data, str):
                    image_data = base64.b64decode(raw_data)
                else:
                    image_data = raw_data
                mime_type = inline_mime or "image/jpeg"
                return {
                    "image": image_data,
                    "mime_type": mime_type,
                    "prompt": prompt_text
                }

        diagnostics["candidates"].append(candidate_log)

    print(f"GenAI no-image diagnostics: {diagnostics}")
    raise Exception("Model returned no image data.")
