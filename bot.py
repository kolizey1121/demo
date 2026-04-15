from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8322728135:AAFPF09wYA94wtrhUn-4HLgxJwAGd_WMsrw"


# /start команда
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(
                "🚀 Открыть Mini App",
                web_app=WebAppInfo(url="https://orkhangel.ru")
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Привет! Нажми кнопку ниже 👇",
        reply_markup=reply_markup
    )


# /help команда (по желанию)
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Напиши /start чтобы открыть Mini App")


def main():
    # создаём приложение
    application = Application.builder().token(TOKEN).build()

    # handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    print("✅ Бот запущен!")

    # ВАЖНО: без asyncio.run()
    application.run_polling()


if __name__ == "__main__":
    main()