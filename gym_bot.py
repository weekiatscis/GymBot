import datetime
import logging
import os
import sqlite3
from collections import defaultdict

import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, PollAnswerHandler, ContextTypes

# ─── CONFIG ───────────────────────────────────────────
TOKEN    = os.environ["TOKEN"]
CHAT_ID  = int(os.environ["CHAT_ID"])
POLL_HOUR   = 20
POLL_MINUTE = 0
NUDGE_HOUR  = 23
NUDGE_MINUTE = 0
TIMEZONE = "Asia/Singapore"
DB_PATH  = os.environ.get("DB_PATH", "./gym_log.db")
# ──────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS gym_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            user_name   TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            chose_yes   INTEGER NOT NULL,
            timestamp   TEXT    NOT NULL
        )
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_user_date
        ON gym_log (user_id, date)
    """)
    con.commit()
    con.close()


async def send_gym_poll(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_poll(
        chat_id=CHAT_ID,
        question="🏋️ Did you go to the gym today?",
        options=["✅ Yes!", "❌ No"],
        is_anonymous=False,
    )


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer    = update.poll_answer
    user_id   = answer.user.id
    user_name = answer.user.first_name
    chose_yes = 0 in answer.option_ids

    tz        = pytz.timezone(TIMEZONE)
    now_sgt   = datetime.datetime.now(tz)
    date_sgt  = now_sgt.strftime("%Y-%m-%d")
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR REPLACE INTO gym_log (user_id, user_name, date, chose_yes, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, user_name, date_sgt, int(chose_yes), timestamp),
    )
    con.commit()
    con.close()

    response = "Nice work! 💪" if chose_yes else "Get after it tomorrow! 😤"
    await context.bot.send_message(chat_id=CHAT_ID, text=f"{user_name}: {response}")


def build_weekly_summary() -> str:
    tz    = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()

    monday     = today - datetime.timedelta(days=today.weekday())
    sunday     = monday + datetime.timedelta(days=6)
    week_dates = [monday + datetime.timedelta(days=i) for i in range(7)]
    day_labels = {d: d.strftime("%a") for d in week_dates}

    monday_str = monday.strftime("%a %-d %b")
    sunday_str = sunday.strftime("%a %-d %b")
    header = f"📊 This Week's Gym Stats ({monday_str} – {sunday_str})"

    con  = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT user_name, date FROM gym_log "
        "WHERE date >= ? AND date <= ? AND chose_yes = 1 "
        "ORDER BY user_name, date",
        (monday.isoformat(), sunday.isoformat()),
    ).fetchall()
    con.close()

    user_days: dict[str, list[str]] = defaultdict(list)
    for user_name, date_str in rows:
        d = datetime.date.fromisoformat(date_str)
        user_days[user_name].append(day_labels[d])

    if not user_days:
        return header + "\nNo gym sessions logged this week yet."

    lines = [header]
    for name in sorted(user_days):
        days_hit = user_days[name]
        lines.append(f"{name}: {len(days_hit)}/7 days ✅ [{', '.join(days_hit)}]")
    return "\n".join(lines)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_weekly_summary())


async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=CHAT_ID, text=build_weekly_summary())


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz    = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()

    # Parse optional day count argument, e.g. /history 7
    try:
        days = int(context.args[0]) if context.args else 14
        days = max(1, min(days, 60))  # clamp between 1 and 60
    except (ValueError, IndexError):
        days = 14

    dates = [today - datetime.timedelta(days=i) for i in range(days - 1, -1, -1)]
    from_date = dates[0].isoformat()
    to_date   = dates[-1].isoformat()

    con  = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT user_name, date, chose_yes FROM gym_log "
        "WHERE date >= ? AND date <= ? ORDER BY date, user_name",
        (from_date, to_date),
    ).fetchall()
    # Get known users from this period
    all_users = sorted({r[0] for r in rows}) if rows else []
    con.close()

    if not all_users:
        await update.message.reply_text(f"No data for the last {days} days.")
        return

    # Build lookup: (user, date) -> chose_yes
    log: dict[tuple[str, str], int] = {(r[0], r[1]): r[2] for r in rows}

    header = f"📅 Last {days} Days\n{'Date':<12}" + "".join(f"{u:<10}" for u in all_users)
    lines  = [header, "─" * (12 + 10 * len(all_users))]
    for d in dates:
        ds   = d.isoformat()
        label = d.strftime("%-d %b %a")
        cells = ""
        for u in all_users:
            val = log.get((u, ds))
            if val is None:
                cells += f"{'–':<10}"
            elif val == 1:
                cells += f"{'✅':<10}"
            else:
                cells += f"{'❌':<10}"
        lines.append(f"{label:<12}{cells}")

    await update.message.reply_text("```\n" + "\n".join(lines) + "\n```", parse_mode="Markdown")


async def send_nudge(context: ContextTypes.DEFAULT_TYPE):
    tz       = pytz.timezone(TIMEZONE)
    today    = datetime.datetime.now(tz).strftime("%Y-%m-%d")

    con  = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT user_name FROM gym_log WHERE date = ?", (today,)
    ).fetchall()
    con.close()

    answered = {r[0] for r in rows}

    # Get all known users from recent history
    con   = sqlite3.connect(DB_PATH)
    known = con.execute(
        "SELECT DISTINCT user_name FROM gym_log ORDER BY timestamp DESC LIMIT 20"
    ).fetchall()
    con.close()
    all_users = {r[0] for r in known}

    missing = all_users - answered
    if missing:
        names = ", ".join(sorted(missing))
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"Oi {names}, did you go to the gym today? 👀 Answer the poll!",
        )


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("history", history_command))

    tz = pytz.timezone(TIMEZONE)

    # Daily gym poll at 8:00 PM SGT
    app.job_queue.run_daily(
        send_gym_poll,
        time=datetime.time(POLL_HOUR, POLL_MINUTE, 0, tzinfo=tz),
    )

    # Auto weekly summary every Sunday at 9:00 PM SGT
    # Note: days=(0,) means Sunday in python-telegram-bot's APScheduler mapping
    app.job_queue.run_daily(
        send_weekly_summary,
        time=datetime.time(21, 0, 0, tzinfo=tz),
        days=(0,),
    )

    # Nudge unanswered users at 11:00 PM SGT
    app.job_queue.run_daily(
        send_nudge,
        time=datetime.time(NUDGE_HOUR, NUDGE_MINUTE, 0, tzinfo=tz),
    )

    print("Gym bot is running!")
    app.run_polling()


if __name__ == "__main__":
    main()
