import logging
import os
import pytz
from telegram import Update
from telegram.ext import Application, PollAnswerHandler, ContextTypes

# ─── CONFIG ───────────────────────────────────────────
import os

TOKEN = os.environ["TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
POLL_HOUR = 1        # change to your preferred hour
POLL_MINUTE = 40
TIMEZONE = "Asia/Singapore"  
# ──────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)

async def send_gym_poll(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_poll(
        chat_id=CHAT_ID,
        question="🏋️ Did you go to the gym today?",
        options=["✅ Yes!", "❌ No"],
        is_anonymous=False,
    )

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user = answer.user.first_name
    chose_yes = 0 in answer.option_ids
    response = "Nice work! 💪" if chose_yes else "Get after it tomorrow! 😤"
    await context.bot.send_message(chat_id=CHAT_ID, text=f"{user}: {response}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    tz = pytz.timezone(TIMEZONE)
    app.job_queue.run_daily(
        send_gym_poll,
        time=tz.localize(
            __import__("datetime").datetime.now().replace(
                hour=POLL_HOUR, minute=POLL_MINUTE, second=0, microsecond=0
            )
        ).timetz(),
    )

    print("✅ Gym bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()