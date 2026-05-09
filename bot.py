import os
import json
import anthropic
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, filters, ContextTypes
from telegram.constants import ParseMode

# --- Config ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# --- States ---
CHOOSE_POSITION, ENTER_CUSTOM_POSITION, ENTER_REQUIREMENTS, ENTER_RESUME = range(4)

POSITIONS = [
    "Менеджер по продажам",
    "Руководитель отдела",
    "Специалист по маркетингу",
    "Финансовый аналитик",
    "HR-менеджер",
    "Разработчик ПО",
    "Операционный директор",
    "Другая должность",
]

SYSTEM_PROMPT = """Ты — опытный HR-эксперт с 15-летним опытом оценки кандидатов.
Твоя задача — провести структурированный анализ резюме и вернуть результат СТРОГО в формате JSON.
Верни ТОЛЬКО валидный JSON без markdown, без пояснений, без текста вне JSON.

Формат ответа:
{
  "name": "Имя кандидата или 'Не указано'",
  "score": число от 0 до 100,
  "verdict": "invite" | "review" | "decline",
  "verdict_label": "Пригласить на интервью" | "Требует доп. проверки" | "Отказать",
  "strengths": ["сильная сторона 1", "сильная сторона 2", "сильная сторона 3"],
  "risks": ["риск 1", "риск 2"],
  "questions": ["вопрос 1", "вопрос 2", "вопрос 3", "вопрос 4"],
  "summary": "Краткий вывод 2-3 предложения"
}"""


def format_result(r: dict) -> str:
    verdict_emoji = {"invite": "✅", "review": "🟡", "decline": "❌"}.get(r.get("verdict", ""), "❓")
    score = r.get("score", 0)
    score_bar = "█" * (score // 10) + "░" * (10 - score // 10)

    strengths = "\n".join(f"  ▸ {s}" for s in r.get("strengths", []))
    risks = "\n".join(f"  ▸ {s}" for s in r.get("risks", []))
    questions = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(r.get("questions", [])))

    return (
        f"👤 *{r.get('name', 'Не указано')}*\n"
        f"\n"
        f"📊 *Балл соответствия:* {score}/100\n"
        f"`{score_bar}`\n"
        f"\n"
        f"{verdict_emoji} *{r.get('verdict_label', '')}*\n"
        f"\n"
        f"📝 *Вывод:*\n{r.get('summary', '')}\n"
        f"\n"
        f"💪 *Сильные стороны:*\n{strengths}\n"
        f"\n"
        f"⚠️ *Зоны риска:*\n{risks}\n"
        f"\n"
        f"❓ *Вопросы для интервью:*\n{questions}"
    )


# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[p] for p in POSITIONS]
    await update.message.reply_text(
        "👋 Привет! Я помогу оценить кандидата по резюме.\n\n"
        "Выберите должность, на которую рассматривается кандидат:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return CHOOSE_POSITION


async def choose_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    position = update.message.text
    if position not in POSITIONS:
        await update.message.reply_text("Пожалуйста, выберите должность из списка.")
        return CHOOSE_POSITION

    if position == "Другая должность":
        await update.message.reply_text(
            "Введите название должности:",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ENTER_CUSTOM_POSITION

    context.user_data["position"] = position
    await update.message.reply_text(
        f"✅ Должность: *{position}*\n\n"
        "Укажите ключевые требования к кандидату (опционально).\n"
        "Или отправьте /skip чтобы пропустить.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove(),
    )
    return ENTER_REQUIREMENTS


async def enter_custom_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["position"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Должность: *{context.user_data['position']}*\n\n"
        "Укажите ключевые требования к кандидату (опционально).\n"
        "Или отправьте /skip чтобы пропустить.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ENTER_REQUIREMENTS


async def enter_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["requirements"] = update.message.text.strip()
    await update.message.reply_text(
        "📄 Отлично! Теперь вставьте текст резюме кандидата:",
    )
    return ENTER_RESUME


async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["requirements"] = ""
    await update.message.reply_text(
        "📄 Вставьте текст резюме кандидата:",
    )
    return ENTER_RESUME


async def enter_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    resume = update.message.text.strip()
    position = context.user_data.get("position", "")
    requirements = context.user_data.get("requirements", "")

    await update.message.reply_text("⏳ Анализирую резюме, подождите 10–20 секунд...")

    user_message = (
        f"Должность: {position}\n"
        f"{('Требования:\n' + requirements + '\n') if requirements else ''}"
        f"\nРезюме кандидата:\n{resume}"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        result = json.loads(text.replace("```json", "").replace("```", "").strip())
        formatted = format_result(result)
        await update.message.reply_text(formatted, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка анализа: {str(e)}\nПопробуйте ещё раз — /start")
        return ConversationHandler.END

    await update.message.reply_text(
        "Оценить ещё одного кандидата? → /start",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено. Для нового анализа — /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# --- Main ---

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_position)],
            ENTER_CUSTOM_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_custom_position)],
            ENTER_REQUIREMENTS: [
                CommandHandler("skip", skip_requirements),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_requirements),
            ],
            ENTER_RESUME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_resume)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
