import os
import html
import time
import requests
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from storage import Storage
from gemini import analyze_style, generate_final_image

# Инициализация диспетчера
dp = Dispatcher()

# Глобальный бот нужен только для локального поллинга, 
# в проде он будет создаваться внутри вебхука.
_global_token = os.environ.get("TELEGRAM_BOT_TOKEN")
bot = Bot(token=_global_token) if _global_token else None

# --- КЛАВИАТУРЫ ---
def get_params_keyboard(params):
    r = params.get('ratio', '9:16')
    q = params.get('quality', '2K')
    
    kb = [
        [
            KeyboardButton(text=f"{'✅ ' if r == '9:16' else ''}9:16"),
            KeyboardButton(text=f"{'✅ ' if r == '1:1' else ''}1:1"),
            KeyboardButton(text=f"{'✅ ' if r == '3:4' else ''}3:4")
        ],
        [
            KeyboardButton(text=f"{'✅ ' if q == '1K' else ''}1K"),
            KeyboardButton(text=f"{'✅ ' if q == '2K' else ''}2K")
        ],
        [KeyboardButton(text="🚀 Генерировать"), KeyboardButton(text="❌ Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

menus = {
    "main": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="🖼 По референсу"), KeyboardButton(text="✍️ По описанию")]
    ], resize_keyboard=True),
    
    "profile": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📸 Загрузить/Обновить фото")],
        [KeyboardButton(text="👀 Цвет глаз"), KeyboardButton(text="💇‍♀️ Цвет волос")],
        [KeyboardButton(text="📏 Длина волос"), KeyboardButton(text="⬅️ Назад")]
    ], resize_keyboard=True),
    
    "yes_no": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Да"), KeyboardButton(text="➕ Нет, разовая генерация")]
    ], resize_keyboard=True),
    
    "eyes": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Голубые"), KeyboardButton(text="Зеленые")],
        [KeyboardButton(text="Карие"), KeyboardButton(text="Серые")],
        [KeyboardButton(text="Черные"), KeyboardButton(text="Разные")]
    ], resize_keyboard=True, one_time_keyboard=True),
    
    "hair_color": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Блонд"), KeyboardButton(text="Русые"), KeyboardButton(text="Каштановые")],
        [KeyboardButton(text="Черные"), KeyboardButton(text="Рыжие"), KeyboardButton(text="Цветные")]
    ], resize_keyboard=True, one_time_keyboard=True),

    "hair_length": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Каре"), KeyboardButton(text="Средние")],
        [KeyboardButton(text="Длинные"), KeyboardButton(text="Очень длинные")],
        [KeyboardButton(text="Лысый/Ежик")]
    ], resize_keyboard=True, one_time_keyboard=True),

    "result": ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔁 Повторить")],
        [KeyboardButton(text="🏠 В главное меню")]
    ], resize_keyboard=True)
}

MAX_CAPTION_LEN = 1024
download_cache = {}

def _build_result_caption(prompt_text: str) -> str:
    prompt_for_user = "\n".join(
        line for line in (prompt_text or "").splitlines()
        if "СУБЪЕКТ: человек с первого изображения." not in line
    ).strip()
    caption_prefix = "Промпт:\n"
    allowed_prompt_len = max(0, MAX_CAPTION_LEN - len(caption_prefix))
    truncated_prompt = prompt_for_user[:allowed_prompt_len]
    escaped_prompt = html.escape(truncated_prompt or "-")
    return f"<blockquote expandable>Промпт:\n{escaped_prompt}</blockquote>"

def _quality_label(quality: str) -> str:
    return (quality or "2K").replace("K", "К")

def _get_download_keyboard(quality: str, generation_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⬇️ Скачать файлом ({_quality_label(quality)})",
                    callback_data=f"download_original:{generation_id}"
                )
            ]
        ]
    )

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def download_file(bot_instance: Bot, file_id: str) -> bytes:
    file_info = await bot_instance.get_file(file_id)
    file_path = file_info.file_path
    # Скачиваем файл напрямую через URL Telegram API
    # В aiogram есть bot.download, но manual request иногда надежнее для байтов в памяти
    url = f"https://api.telegram.org/file/bot{bot_instance.token}/{file_path}"
    response = requests.get(url)
    return response.content

def _normalize_hints(raw_value: str) -> str:
    value = (raw_value or "").strip()
    return "" if value == "-" else value

async def _run_generation(message: types.Message, user_id: int, req_data: dict):
    params = req_data.get("params", {"ratio": "9:16", "quality": "2K"})
    await message.answer("🍌 Генерирую...", reply_markup=ReplyKeyboardRemove())
    Storage.set_session(user_id, "PROCESSING")

    try:
        face_bytes = await download_file(message.bot, req_data["userPhotoId"])

        style_bytes = None
        style_desc = req_data.get("styleDesc", "")
        is_text_flow = not bool(req_data.get("refPhotoId"))

        if (not is_text_flow) and req_data.get("refPhotoId"):
            await message.bot.send_chat_action(chat_id=user_id, action="typing")
            style_bytes = await download_file(message.bot, req_data["refPhotoId"])
            if not style_desc:
                style_desc = await analyze_style(style_bytes)

        await message.bot.send_chat_action(chat_id=user_id, action="upload_photo")

        result = await generate_final_image(
            face_bytes=face_bytes,
            style_bytes=style_bytes,
            user_traits=req_data.get("userTraits", {}),
            style_desc=style_desc,
            user_hints=req_data.get("userHints"),
            params=params
        )

        mime_type = (result.get("mime_type") or "image/jpeg").lower()
        ext = "jpg" if "jpeg" in mime_type else "png" if "png" in mime_type else "jpg"
        image_bytes = result["image"]
        print(f"Generated image: mime={mime_type}, bytes={len(image_bytes)}")
        image_file = BufferedInputFile(image_bytes, filename=f"result.{ext}")
        quality = params.get("quality", "2K")
        generation_id = f"{user_id}:{int(time.time() * 1000)}"
        caption = _build_result_caption(result.get("prompt", ""))
        await message.answer_photo(
            image_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=_get_download_keyboard(quality, generation_id)
        )
        await message.answer("Что дальше?", reply_markup=menus["result"])

        download_cache[generation_id] = {
            "user_id": user_id,
            "image": image_bytes,
            "mime_type": mime_type,
            "quality": quality,
        }

        last_req = req_data.copy()
        last_req["styleDesc"] = style_desc
        Storage.set_session(user_id, "RESULT_VIEW", {"lastReq": last_req})
    except Exception as e:
        print(f"Gen Error: {e}")
        Storage.set_session(user_id, "IDLE", reset_data=True)
        await message.answer(f"Ошибка: {str(e)}", reply_markup=menus["main"])

async def reply_with_profile(message: types.Message, user: dict):
    text = f"👤 *Ваш профиль:*\n\n"
    text += f"👀 Глаза: {user.get('eyes', 'Не указано')}\n"
    text += f"💇‍♀️ Цвет волос: {user.get('hairColor', 'Не указано')}\n"
    text += f"📏 Длина волос: {user.get('hairLength', 'Не указано')}\n"
    text += f"📸 Фото: {'✅ Загружено' if user.get('photoId') else '❌ Не загружено'}"
    
    try:
        if user.get('photoId'):
            await message.answer_photo(user['photoId'], caption=text, parse_mode="Markdown", reply_markup=menus["profile"])
        else:
            await message.answer(text, parse_mode="Markdown", reply_markup=menus["profile"])
    except Exception as e:
        print(f"Error sending profile: {e}")
        await message.answer(text + "\n(Фото недоступно)", parse_mode="Markdown", reply_markup=menus["profile"])

# --- ХЕНДЛЕРЫ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    Storage.save_user(user_id, {"username": message.from_user.username})
    Storage.set_session(user_id, "IDLE", reset_data=True)
    await message.answer(
        "Привет! Я Nano Banana Bot 🍌.\n\nСоздавай фотореалистичные арты со своим лицом.\nНачни с настройки профиля!",
        reply_markup=menus["main"]
    )

@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    caption = message.caption
    user_input = (text if text is not None else caption) or ""
    photo = message.photo
    
    # Инициализация пользователя если нет
    if not Storage.get_user(user_id):
        Storage.save_user(user_id, {"username": message.from_user.username})
    
    session = Storage.get_session(user_id)
    state = session["state"]
    data = session["data"]

    # Глобальная навигация
    if text in ["⬅️ Назад", "🏠 В главное меню"]:
        Storage.set_session(user_id, "IDLE", reset_data=True)
        await message.answer("Главное меню", reply_markup=menus["main"])
        return

    if text == "👤 Мой профиль":
        Storage.set_session(user_id, "IDLE", reset_data=True)
        await reply_with_profile(message, Storage.get_user(user_id))
        return

    # STATE: IDLE
    if state == "IDLE":
        if text == "📸 Загрузить/Обновить фото":
            Storage.set_session(user_id, "PROFILE_EDIT_PHOTO")
            await message.answer("Отправь своё фото (селфи).")
            return
        if text == "👀 Цвет глаз":
            Storage.set_session(user_id, "PROFILE_EDIT_EYES")
            await message.answer("Выбери цвет глаз:", reply_markup=menus["eyes"])
            return
        if text == "💇‍♀️ Цвет волос":
            Storage.set_session(user_id, "PROFILE_EDIT_HAIR_COLOR")
            await message.answer("Выбери цвет волос:", reply_markup=menus["hair_color"])
            return
        if text == "📏 Длина волос":
            Storage.set_session(user_id, "PROFILE_EDIT_HAIR_LENGTH")
            await message.answer("Выбери длину волос:", reply_markup=menus["hair_length"])
            return
        if text == "🖼 По референсу":
            Storage.set_session(user_id, "GEN_REF_PROFILE_CHOICE", reset_data=True)
            await message.answer("Использовать параметры из профиля?", reply_markup=menus["yes_no"])
            return
        if text == "✍️ По описанию":
            Storage.set_session(user_id, "GEN_TEXT_PROFILE_CHOICE", reset_data=True)
            await message.answer("Использовать параметры из профиля?", reply_markup=menus["yes_no"])
            return
        
        if text and not text.startswith("/"):
            await message.answer("Используй меню 👇", reply_markup=menus["main"])
            return

    # STATE: PROFILE EDIT
    if state == "PROFILE_EDIT_PHOTO":
        if not photo:
            await message.answer("Жду фото (не файл).")
            return
        photo_id = photo[-1].file_id
        Storage.save_user(user_id, {"photoId": photo_id})
        Storage.set_session(user_id, "IDLE")
        await reply_with_profile(message, Storage.get_user(user_id))
        return
    
    if state.startswith("PROFILE_EDIT_"):
        field_map = {
            "PROFILE_EDIT_EYES": "eyes",
            "PROFILE_EDIT_HAIR_COLOR": "hairColor",
            "PROFILE_EDIT_HAIR_LENGTH": "hairLength"
        }
        field = field_map.get(state)
        if field:
            Storage.save_user(user_id, {field: text})
            Storage.set_session(user_id, "IDLE")
            await reply_with_profile(message, Storage.get_user(user_id))
            return

    # STATE: GEN SETUP - PROFILE CHOICE
    if state in ["GEN_REF_PROFILE_CHOICE", "GEN_TEXT_PROFILE_CHOICE"]:
        is_ref = "REF" in state
        if text == "✅ Да":
            u = Storage.get_user(user_id)
            if not u.get("photoId"):
                await message.answer("В профиле нет фото! Загрузи его в меню 'Мой профиль'.")
                return
            
            next_state = "GEN_REF_WAIT_IMAGE" if is_ref else "GEN_TEXT_WAIT_HINTS"
            Storage.set_session(user_id, next_state, {
                "useProfile": True,
                "userPhotoId": u["photoId"],
                "userTraits": {"eyes": u.get("eyes"), "hairColor": u.get("hairColor"), "hairLength": u.get("hairLength")}
            })
            await message.answer("Отправь референс (картинку стиля)." if is_ref else "Опиши, что хочешь увидеть.", reply_markup=ReplyKeyboardRemove())
            return
        
        if text and "Нет" in text:
            next_state = "GEN_REF_TEMP_PHOTO" if is_ref else "GEN_TEXT_TEMP_PHOTO"
            Storage.set_session(user_id, next_state, {"useProfile": False})
            await message.answer("Отправь свое фото для этой генерации.")
            return

    # STATE: TEMP DATA COLLECTION
    if "_TEMP_PHOTO" in state:
        if not photo:
            await message.answer("Нужно фото.")
            return
        is_ref = "REF" in state
        next_state = "GEN_REF_TEMP_EYES" if is_ref else "GEN_TEXT_TEMP_EYES"
        Storage.set_session(user_id, next_state, {"userPhotoId": photo[-1].file_id})
        await message.answer("Цвет глаз?", reply_markup=menus["eyes"])
        return

    if "_TEMP_EYES" in state:
        is_ref = "REF" in state
        traits = data.get("userTraits", {})
        traits["eyes"] = text
        next_state = "GEN_REF_TEMP_HAIR" if is_ref else "GEN_TEXT_TEMP_HAIR"
        Storage.set_session(user_id, next_state, {"userTraits": traits})
        await message.answer("Цвет волос?", reply_markup=menus["hair_color"])
        return

    if "_TEMP_HAIR" in state:
        is_ref = "REF" in state
        traits = data.get("userTraits", {})
        traits["hairColor"] = text
        next_state = "GEN_REF_WAIT_IMAGE" if is_ref else "GEN_TEXT_WAIT_HINTS"
        Storage.set_session(user_id, next_state, {"userTraits": traits})
        await message.answer("Теперь референс." if is_ref else "Опиши идею.", reply_markup=ReplyKeyboardRemove())
        return

    # STATE: REF IMAGE & HINTS
    if state == "GEN_REF_WAIT_IMAGE":
        if not photo:
            await message.answer("Жду картинку.")
            return
        def_params = {"ratio": "9:16", "quality": "2K"}
        inline_hints = _normalize_hints(caption)
        Storage.set_session(
            user_id,
            "GEN_REF_WAIT_PARAMS",
            {"refPhotoId": photo[-1].file_id, "userHints": inline_hints, "params": def_params}
        )
        await message.answer(
            "Можешь добавить пожелания к результату текстом (по желанию) "
            "или сразу нажать «🚀 Генерировать».",
            reply_markup=get_params_keyboard(def_params)
        )
        return

    if "WAIT_HINTS" in state:
        hints = _normalize_hints(user_input)
        is_ref = "REF" in state
        next_state = "GEN_REF_WAIT_PARAMS" if is_ref else "GEN_TEXT_WAIT_PARAMS"
        def_params = {"ratio": "9:16", "quality": "2K"}
        Storage.set_session(user_id, next_state, {"userHints": hints, "params": def_params})
        await message.answer(
            "Добавь текстовые пожелания (по желанию) и выбери параметры. "
            "Можно сразу нажать «🚀 Генерировать».",
            reply_markup=get_params_keyboard(def_params)
        )
        return

    # STATE: PARAMS & EXECUTE
    if "WAIT_PARAMS" in state:
        if not text:
            await message.answer("Используй кнопки параметров или отправь текстовые пожелания.", reply_markup=get_params_keyboard(data.get("params", {"ratio": "9:16", "quality": "2K"})))
            return

        if text == "❌ Отмена":
            Storage.set_session(user_id, "IDLE", reset_data=True)
            await message.answer("Отмена", reply_markup=menus["main"])
            return
        
        params = data.get("params", {"ratio": "9:16", "quality": "2K"})
        changed = False

        if "9:16" in text: params["ratio"] = "9:16"; changed = True
        if "1:1" in text: params["ratio"] = "1:1"; changed = True
        if "3:4" in text: params["ratio"] = "3:4"; changed = True
        if "1K" in text: params["quality"] = "1K"; changed = True
        if "2K" in text: params["quality"] = "2K"; changed = True

        if changed:
            Storage.set_session(user_id, state, {"params": params})
            await message.answer(f"Выбрано: {text}", reply_markup=get_params_keyboard(params))
            return

        normalized_text = _normalize_hints(text)
        if normalized_text:
            Storage.set_session(user_id, state, {"userHints": normalized_text, "params": params})
            await message.answer(
                "Текстовые пожелания обновил. Можно нажимать «🚀 Генерировать».",
                reply_markup=get_params_keyboard(params)
            )
            return

        if text == "🚀 Генерировать":
            req_data = data.copy()
            req_data["params"] = params
            await _run_generation(message, user_id, req_data)
            return

        await message.answer(
            "Можно отправить текстовые пожелания или выбрать параметры кнопками.",
            reply_markup=get_params_keyboard(params)
        )
        return

    # STATE: RESULT
    if state == "RESULT_VIEW":
        if text == "🔁 Повторить":
            last = data.get("lastReq")
            if not last:
                Storage.set_session(user_id, "IDLE", reset_data=True)
                await message.answer("Не удалось восстановить прошлый запрос.", reply_markup=menus["main"])
                return
            await _run_generation(message, user_id, last)
            return
        
        Storage.set_session(user_id, "IDLE", reset_data=True)
        await message.answer("Меню", reply_markup=menus["main"])
        return

@dp.callback_query(F.data.startswith("download_original:"))
async def download_original_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    generation_id = callback.data.split(":", 1)[1] if callback.data else ""
    cached = download_cache.get(generation_id)

    if not cached or cached.get("user_id") != user_id:
        await callback.answer("Оригинал недоступен. Сгенерируйте заново.", show_alert=True)
        return

    mime_type = (cached.get("mime_type") or "image/jpeg").lower()
    ext = "jpg" if "jpeg" in mime_type else "png" if "png" in mime_type else "jpg"
    quality = cached.get("quality", "2K")
    image_bytes = cached["image"]

    document = BufferedInputFile(image_bytes, filename=f"result_{quality}.{ext}")
    await callback.message.answer_document(
        document=document,
        caption=f"Оригинал без сжатия ({_quality_label(quality)})"
    )

    # После отправки файла кнопка больше не нужна: файл уже в чате.
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Файл отправлен")
