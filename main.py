import os
import modal
from aiogram import Bot
from bot import dp, bot as local_bot
from aiogram.types import Update

# Определение образа контейнера
image = (
    modal.Image.debian_slim()
    .pip_install(
        "aiogram>=3.0.0",
        "google-genai", 
        "requests",
        "pillow",
        "fastapi[standard]"
    )
)

app = modal.App("nano-banana-bot", image=image)

# Подключаем секреты (API ключи)
secrets = [modal.Secret.from_name("nano-banana-bot-secrets")]

@app.function(secrets=secrets, keep_warm=1)
@modal.web_endpoint(method="POST")
async def telegram_webhook(request: dict):
    """
    Вебхук, который принимает обновления от Telegram.
    Modal автоматически выдаст HTTPS ссылку.
    """
    try:
        # Инициализируем бота ЗДЕСЬ, внутри функции, где есть секреты
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
             return {"status": "error", "message": "No token found"}
        
        # Создаем временный экземпляр бота для обработки этого запроса
        webhook_bot = Bot(token=token)
        
        update = Update.model_validate(request)
        await dp.feed_update(webhook_bot, update)
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing update: {e}")
        return {"status": "error", "message": str(e)}

@app.function(secrets=secrets)
async def set_webhook(url: str):
    """Функция для ручной установки вебхука через `modal run`"""
    # Здесь тоже используем локальный инстанс, так как секреты доступны
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    temp_bot = Bot(token=token)
    await temp_bot.set_webhook(url)
    print(f"✅ Webhook set to: {url}")

# Локальный запуск для тестов (polling)
if __name__ == "__main__":
    import asyncio
    # Для локального запуска используем bot из bot.py, который берет токен из локального env
    if local_bot:
        asyncio.run(dp.start_polling(local_bot))
    else:
        print("Error: TELEGRAM_BOT_TOKEN not found for local polling.")
