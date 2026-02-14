import os
import modal
import json
import time

def _truncate(value: str, limit: int = 120) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[:limit] + "...<truncated>"

def _extract_update_context(update) -> dict:
    ctx = {
        "update_id": getattr(update, "update_id", None),
        "event_type": "unknown",
        "user_id": None,
        "chat_id": None,
        "text": "",
        "callback_data": "",
    }

    message = getattr(update, "message", None)
    callback_query = getattr(update, "callback_query", None)

    if message:
        ctx["event_type"] = "message"
        ctx["user_id"] = getattr(getattr(message, "from_user", None), "id", None)
        ctx["chat_id"] = getattr(getattr(message, "chat", None), "id", None)
        ctx["text"] = _truncate(getattr(message, "text", None) or getattr(message, "caption", None) or "")
    elif callback_query:
        ctx["event_type"] = "callback_query"
        ctx["user_id"] = getattr(getattr(callback_query, "from_user", None), "id", None)
        callback_message = getattr(callback_query, "message", None)
        ctx["chat_id"] = getattr(getattr(callback_message, "chat", None), "id", None)
        ctx["callback_data"] = _truncate(getattr(callback_query, "data", None) or "")

    return ctx

# Определение образа контейнера
image = (
    modal.Image.debian_slim()
    .pip_install(
        "aiogram>=3.0.0",
        "google-genai",
        "requests",
        "pillow",
        "fastapi[standard]",
    )
    # Добавляем локальные файлы проекта в образ (без .venv, .git, node_modules)
    .add_local_dir(
        ".",
        remote_path="/root",
        ignore=[".venv", ".git", "node_modules", "__pycache__", ".DS_Store"],
    )
)

app = modal.App("nano-banana-bot", image=image)

# Подключаем секреты (API ключи)
secrets = [modal.Secret.from_name("nano-banana-bot-secrets")]

@app.function(secrets=secrets, min_containers=1)
@modal.fastapi_endpoint(method="POST")
async def telegram_webhook(request: dict):
    """
    Вебхук, который принимает обновления от Telegram.
    Modal автоматически выдаст HTTPS ссылку.
    """
    try:
        from aiogram import Bot
        from aiogram.types import Update
        from bot import dp
        from storage import Storage

        # Инициализируем бота ЗДЕСЬ, внутри функции, где есть секреты
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
             return {"status": "error", "message": "No token found"}
        
        # Создаем временный экземпляр бота для обработки этого запроса
        webhook_bot = Bot(token=token)
        
        update = Update.model_validate(request)
        ctx = _extract_update_context(update)
        user_id = ctx.get("user_id")
        session_before = Storage.get_session(user_id)["state"] if user_id else None
        started_at = time.perf_counter()

        print(f"Webhook start: {json.dumps({**ctx, 'session_before': session_before}, ensure_ascii=False)}")

        await dp.feed_update(webhook_bot, update)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        session_after = Storage.get_session(user_id)["state"] if user_id else None
        print(
            f"Webhook done: {json.dumps({**ctx, 'session_after': session_after, 'elapsed_ms': elapsed_ms}, ensure_ascii=False)}"
        )
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing update: {e}")
        return {"status": "error", "message": str(e)}

@app.function(secrets=secrets)
async def set_webhook(url: str):
    """Функция для ручной установки вебхука через `modal run`"""
    from aiogram import Bot

    # Здесь тоже используем локальный инстанс, так как секреты доступны
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    temp_bot = Bot(token=token)
    await temp_bot.set_webhook(url)
    print(f"✅ Webhook set to: {url}")

# Локальный запуск для тестов (polling)
if __name__ == "__main__":
    import asyncio
    from bot import dp, bot as local_bot

    # Для локального запуска используем bot из bot.py, который берет токен из локального env
    if local_bot:
        asyncio.run(dp.start_polling(local_bot))
    else:
        print("Error: TELEGRAM_BOT_TOKEN not found for local polling.")
