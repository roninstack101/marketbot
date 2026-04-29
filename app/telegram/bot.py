"""
Telegram bot for ClaudBot.

Run with:  python -m app.telegram.bot

Flow:
  User message  → submit task → poll every 2s → reply when done
  waiting_for_input → send question → next user message = answer
  pending_approval  → send inline Approve / Reject buttons
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
from app.telegram.api import approve, get_task, reject, respond_to_task, submit_task

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
settings = get_settings()

# ── Per-chat state ────────────────────────────────────────────────────────────
# { chat_id: { "task_id": str, "waiting_for_input": bool, "approval_id": str|None } }
_state: dict[int, dict] = {}

POLL_INTERVAL = 2   # seconds between status checks
MAX_POLLS = 300     # 10 minutes max wait


# ── Helpers ───────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n\n…(truncated)"


async def _send_result(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send output — as file if it's HTML/very long, otherwise as text."""
    if text.strip().startswith("<!") or text.strip().startswith("<html"):
        bio = io.BytesIO(text.encode())
        bio.name = "output.html"
        await context.bot.send_document(chat_id=chat_id, document=bio, caption="Website generated")
    elif len(text) > 4000:
        # Split into chunks
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await context.bot.send_message(chat_id=chat_id, text=chunk)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text)


async def _poll_task(chat_id: int, task_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Background coroutine: polls task status and sends updates to the user."""
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
            question = (
                task.get("pending_approval", {}) or {}
            ).get("action_summary") or "Please provide more information:"
            _state[chat_id] = {
                "task_id": task_id,
                "waiting_for_input": True,
                "approval_id": None,
            }
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❓ {question}",
            )
            return  # stop polling — resume when user replies

        if status == "pending_approval":
            pa = task.get("pending_approval") or {}
            approval_id = pa.get("approval_id", "")
            summary = pa.get("action_summary", "perform this action")
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
                ]
            ])
            _state[chat_id] = {
                "task_id": task_id,
                "waiting_for_input": False,
                "approval_id": approval_id,
            }
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Approval required: *{summary}*\nAllow the bot to proceed?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            return  # stop polling — resume after button press

        if status in ("failed", "rejected", "cancelled"):
            error = task.get("error") or status
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Task {status}: {error}")
            _state.pop(chat_id, None)
            return

        # still running — keep polling silently

    await context.bot.send_message(chat_id=chat_id, text="⏱ Task timed out. Check status with /status.")


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi! I'm ClaudBot.\n\n"
        "Just send me any task or question:\n"
        "• Write a blog post about AI\n"
        "• Build a website for my brand Nike\n"
        "• What is machine learning?\n"
        "• Debug this Python code: ...\n\n"
        "Commands: /status /cancel /help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*ClaudBot commands*\n\n"
        "/start — Introduction\n"
        "/status — Check current task status\n"
        "/cancel — Cancel the current task\n"
        "/help — Show this message\n\n"
        "*What I can do:*\n"
        "• Answer any question\n"
        "• Write blog posts, emails, social posts\n"
        "• Build websites & landing pages\n"
        "• Generate images\n"
        "• Write & debug code\n"
        "• Research topics from the web\n"
        "• Manage brand voices",
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
    _state.pop(chat_id, None)
    await update.message.reply_text("Task cancelled. Send a new message to start fresh.")


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = _state.get(chat_id)

    # Resume a waiting_for_input task with the user's answer
    if state and state.get("waiting_for_input"):
        task_id = state["task_id"]
        await update.message.reply_text("Got it, resuming…")
        try:
            await respond_to_task(task_id, text)
            _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": None}
            asyncio.create_task(_poll_task(chat_id, task_id, context))
        except Exception as exc:
            await update.message.reply_text(f"❌ Error submitting answer: {exc}")
        return

    # New task
    await update.message.reply_text("⏳ Working on it…")
    try:
        task_id = await submit_task(text, created_by=str(chat_id))
        _state[chat_id] = {"task_id": task_id, "waiting_for_input": False, "approval_id": None}
        asyncio.create_task(_poll_task(chat_id, task_id, context))
    except Exception as exc:
        await update.message.reply_text(f"❌ Failed to submit task: {exc}")


# ── Inline keyboard callback (approve / reject) ───────────────────────────────

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
            await query.edit_message_text("✅ Approved. Resuming task…")
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

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Telegram bot starting (polling)…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
