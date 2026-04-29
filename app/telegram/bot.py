"""
Telegram bot for ClaudBot.

Run with:  python -m app.telegram.bot

Flow:
  New user    → /start → onboarding conversation (name, nickname, role, tone)
  Returning   → /start → welcome back by name
  Any message → submit task → poll → reply when done
  waiting_for_input → send question → next message = answer
  pending_approval  → inline Approve / Reject buttons
"""
import asyncio
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import get_settings
from app.memory.user_store import (
    clear_user_memories,
    delete_user_memory,
    get_user_memories,
    is_onboarded,
    mark_onboarded,
    reset_onboarding,
    save_user_memory,
)
from app.telegram.api import approve, get_task, reject, respond_to_task, submit_task

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
settings = get_settings()

# ── Per-chat task state ───────────────────────────────────────────────────────
_state: dict[int, dict] = {}

# ── Onboarding state ──────────────────────────────────────────────────────────
# {chat_id: {"step": int, "answers": dict}}
_setup: dict[int, dict] = {}

POLL_INTERVAL = 2
MAX_POLLS = 300

_SETUP_QUESTIONS = [
    ("name",     "What's your name?"),
    ("nickname", "What should I call you? (e.g. Yash, Boss, Chief 😄)"),
    ("role",     "What's your role? (e.g. entrepreneur, marketer, developer)"),
    ("tone",     "Preferred tone / language? (e.g. casual English, formal English, Hindi)"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_result(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if text.strip().startswith("<!") or text.strip().lower().startswith("<html"):
        bio = io.BytesIO(text.encode())
        bio.name = "output.html"
        await context.bot.send_document(chat_id=chat_id, document=bio, caption="Website generated")
    elif len(text) > 4000:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await context.bot.send_message(chat_id=chat_id, text=chunk)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text)


async def _poll_task(chat_id: int, task_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    for _ in range(MAX_POLLS):
        await asyncio.sleep(POLL_INTERVAL)
        try:
            task = await get_task(task_id)
        except Exception as exc:
            log.error("poll_error: %s", exc)
            continue

        status = task.get("status")

        if status == "complete":
            output = task.get("final_output") or "Done — no output returned."
            await _send_result(chat_id, output, context)
            _state.pop(chat_id, None)
            return

        if status == "waiting_for_input":
            question = (task.get("pending_approval") or {}).get("action_summary") or "Please provide more information:"
            _state[chat_id] = {"task_id": task_id, "waiting_for_input": True, "approval_id": None}
            await context.bot.send_message(chat_id=chat_id, text=f"❓ {question}")
            return

        if status == "pending_approval":
            pa = task.get("pending_approval") or {}
            approval_id = pa.get("approval_id", "")
            summary = pa.get("action_summary", "perform this action")
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{approval_id}"),
            ]])
            _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": approval_id}
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Approval required: *{summary}*\nAllow the bot to proceed?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            return

        if status in ("failed", "rejected", "cancelled"):
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Task {status}: {task.get('error') or status}")
            _state.pop(chat_id, None)
            return

    await context.bot.send_message(chat_id=chat_id, text="⏱ Task timed out.")


# ── Onboarding ────────────────────────────────────────────────────────────────

async def _ask_setup_question(chat_id: int, step: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, question = _SETUP_QUESTIONS[step]
    await context.bot.send_message(chat_id=chat_id, text=question)


async def _finish_setup(chat_id: int, answers: dict, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = str(chat_id)
    await save_user_memory(uid, f"User's name is {answers['name']}", category="name")
    await save_user_memory(uid, f"Call the user '{answers['nickname']}'", category="nickname")
    await save_user_memory(uid, f"User's role is {answers['role']}", category="role")
    await save_user_memory(uid, f"Preferred tone and language: {answers['tone']}", category="preference")
    await mark_onboarded(uid)   # permanent flag — won't ask again on /start

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"All set, {answers['nickname']}! 🎉\n\n"
            f"I'll remember:\n"
            f"• Name: {answers['name']}\n"
            f"• Role: {answers['role']}\n"
            f"• Tone: {answers['tone']}\n\n"
            "Just send me any task or question to get started.\n"
            "Use /myprofile to see your saved info anytime."
        ),
    )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    uid = str(chat_id)

    if await is_onboarded(uid):
        # Returning user
        memories = await get_user_memories(uid)
        nickname = next(
            (m["memory"].split("'")[1] for m in memories if m["category"] == "nickname"),
            "there",
        )
        await update.message.reply_text(
            f"Welcome back, {nickname}! 👋\n\n"
            "Just send me any task or question.\n"
            "/myprofile — view your saved info\n"
            "/setup — redo your profile\n"
            "/help — all commands"
        )
    else:
        # First-time user — start onboarding once
        _setup[chat_id] = {"step": 0, "answers": {}}
        await update.message.reply_text(
            "👋 Hi! I'm ClaudBot — your AI assistant.\n\n"
            "Before we start, let me learn a bit about you. Just a few quick questions!"
        )
        await _ask_setup_question(chat_id, 0, context)


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicitly redo the profile setup."""
    chat_id = update.effective_chat.id
    await clear_user_memories(str(chat_id))
    await reset_onboarding(str(chat_id))
    _setup[chat_id] = {"step": 0, "answers": {}}
    await update.message.reply_text("Let's update your profile! Starting fresh.")
    await _ask_setup_question(chat_id, 0, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*ClaudBot commands*\n\n"
        "/start — Welcome / onboarding\n"
        "/setup — Redo your profile setup\n"
        "/myprofile — View your saved info\n"
        "/remember <fact> — Save something manually\n"
        "/forget <id> — Delete a memory\n"
        "/clearprofile — Wipe all memories\n"
        "/status — Check current task\n"
        "/cancel — Cancel current task\n"
        "/help — This message\n\n"
        "*What I can do:*\n"
        "• Answer any question\n"
        "• Write blogs, emails, social posts\n"
        "• Build websites & landing pages\n"
        "• Generate images\n"
        "• Write & debug code\n"
        "• Research topics from the web",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state = _state.get(chat_id)
    if not state:
        await update.message.reply_text("No active task.")
        return
    try:
        task = await get_task(state["task_id"])
        await update.message.reply_text(f"Status: *{task['status']}*", parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("Could not fetch task status.")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _setup.pop(chat_id, None)
    _state.pop(chat_id, None)
    await update.message.reply_text("Cancelled. Send a new message to start fresh.")


# ── User memory commands ──────────────────────────────────────────────────────

async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /remember <anything>\nExample: /remember I prefer bullet points")
        return
    await save_user_memory(str(chat_id), text)
    await update.message.reply_text(f"✅ Remembered: {text}")


async def cmd_myprofile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    memories = await get_user_memories(str(chat_id))
    if not memories:
        await update.message.reply_text("No profile yet. Use /setup to create one.")
        return
    lines = [f"`{m['id'][:8]}` [{m['category']}] {m['memory']}" for m in memories]
    text = "🧠 *Your profile:*\n\n" + "\n".join(lines)
    text += "\n\n/forget <id> to remove one • /setup to redo"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /forget <memory-id>\nSee IDs with /myprofile")
        return
    partial_id = context.args[0].strip()
    memories = await get_user_memories(str(chat_id))
    match = next((m for m in memories if m["id"].startswith(partial_id)), None)
    if not match:
        await update.message.reply_text(f"No memory found with ID `{partial_id}`", parse_mode=ParseMode.MARKDOWN)
        return
    if await delete_user_memory(match["id"], str(chat_id)):
        await update.message.reply_text(f"🗑 Forgotten: {match['memory']}")


async def cmd_clearprofile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    count = await clear_user_memories(str(chat_id))
    await update.message.reply_text(f"🗑 Cleared {count} memories.")


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # ── Onboarding in progress ───────────────────────────────────────────────
    if chat_id in _setup:
        setup = _setup[chat_id]
        step = setup["step"]
        key, _ = _SETUP_QUESTIONS[step]
        setup["answers"][key] = text
        step += 1
        setup["step"] = step

        if step < len(_SETUP_QUESTIONS):
            await _ask_setup_question(chat_id, step, context)
        else:
            _setup.pop(chat_id)
            await _finish_setup(chat_id, setup["answers"], context)
        return

    # ── Resume waiting_for_input task ────────────────────────────────────────
    state = _state.get(chat_id)
    if state and state.get("waiting_for_input"):
        task_id = state["task_id"]
        await update.message.reply_text("Got it, resuming…")
        try:
            await respond_to_task(task_id, text)
            _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": None}
            asyncio.create_task(_poll_task(chat_id, task_id, context))
        except Exception as exc:
            await update.message.reply_text(f"❌ Error: {exc}")
        return

    # ── New task ─────────────────────────────────────────────────────────────
    await update.message.reply_text("⏳ Working on it…")
    try:
        task_id = await submit_task(text, created_by=str(chat_id), user_id=str(chat_id))
        _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": None}
        asyncio.create_task(_poll_task(chat_id, task_id, context))
    except Exception as exc:
        await update.message.reply_text(f"❌ Failed to submit task: {exc}")


# ── Inline keyboard callback ──────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    action, approval_id = query.data.split(":", 1)
    state = _state.get(chat_id, {})
    task_id = state.get("task_id")

    try:
        if action == "approve":
            await approve(approval_id, approved_by=str(chat_id))
            await query.edit_message_text("✅ Approved. Resuming…")
            if task_id:
                _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": None}
                asyncio.create_task(_poll_task(chat_id, task_id, context))
        else:
            await reject(approval_id, approved_by=str(chat_id))
            await query.edit_message_text("❌ Rejected. Task stopped.")
            _state.pop(chat_id, None)
    except Exception as exc:
        await query.edit_message_text(f"Error: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("setup",        cmd_setup))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("status",       cmd_status))
    app.add_handler(CommandHandler("cancel",       cmd_cancel))
    app.add_handler(CommandHandler("remember",     cmd_remember))
    app.add_handler(CommandHandler("myprofile",    cmd_myprofile))
    app.add_handler(CommandHandler("forget",       cmd_forget))
    app.add_handler(CommandHandler("clearprofile", cmd_clearprofile))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Telegram bot starting (polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
