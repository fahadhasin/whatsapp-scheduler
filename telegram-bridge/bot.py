import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import contacts as contacts_mod
import nlp
import scheduler_bridge

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation state
CONFIRM = 0


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context) -> None:
    await update.message.reply_text(
        "WhatsApp Scheduler Bot\n\n"
        "Just describe what you want to schedule:\n"
        "  Send Mom a message tomorrow at 9am: Happy birthday!\n"
        "  Remind Dad every Monday at 8am to call me\n\n"
        "Structured commands:\n"
        "  /send <contact> <YYYY-MM-DD> <HH:MM> <message>\n"
        "  /repeat <contact> <min> <hour> <dom> <month> <dow> <message>\n\n"
        "Contacts:\n"
        "  /contacts — list saved contacts\n"
        "  /contacts add <name> <number> — add a contact\n"
        "  /contacts remove <name> — remove a contact\n\n"
        "Schedules:\n"
        "  /list — show your scheduled messages\n"
        "  /cancel <id> — remove a scheduled message\n\n"
        "Phone numbers: country code, no '+' (e.g. 919XXXXXXXXX)\n"
        "Groups: use 'group:Group Name' as the contact's number"
    )


# ── /contacts ─────────────────────────────────────────────────────────────────

async def cmd_contacts(update: Update, context) -> None:
    args = context.args or []

    if not args:
        all_contacts = contacts_mod.list_all()
        if not all_contacts:
            await update.message.reply_text(
                "No contacts saved.\nAdd one: /contacts add <name> <number>"
            )
            return
        lines = [f"  {name}: {number}" for name, number in sorted(all_contacts.items())]
        await update.message.reply_text("Contacts:\n" + "\n".join(lines))
        return

    subcommand = args[0].lower()

    if subcommand == 'add':
        if len(args) < 3:
            await update.message.reply_text("Usage: /contacts add <name> <number>")
            return
        name = args[1]
        number = args[2]
        contacts_mod.add(name, number)
        await update.message.reply_text(f"Saved: {name.lower()} → {number}")

    elif subcommand == 'remove':
        if len(args) < 2:
            await update.message.reply_text("Usage: /contacts remove <name>")
            return
        name = args[1]
        if contacts_mod.remove(name):
            await update.message.reply_text(f"Removed: {name.lower()}")
        else:
            await update.message.reply_text(f"Contact not found: {name.lower()}")

    else:
        await update.message.reply_text(
            "Usage: /contacts [add <name> <number> | remove <name>]"
        )


# ── /list ─────────────────────────────────────────────────────────────────────

async def cmd_list(update: Update, context) -> None:
    schedules = scheduler_bridge.list_tg_schedules()
    if not schedules:
        await update.message.reply_text(
            "No scheduled messages. Just tell me what to schedule."
        )
        return

    lines = []
    for s in schedules:
        kind = "one-time" if s['id'].startswith('tg-once-') else "recurring"
        target_at = s.get('_scheduled_at', '')
        when = target_at if target_at else f"cron: {s['cron']}"
        msg_preview = s['message'][:60] + ('…' if len(s['message']) > 60 else '')
        lines.append(
            f"ID: {s['id']}\n"
            f"  To: {s['to']}\n"
            f"  When: {when} ({kind})\n"
            f"  Msg: {msg_preview}"
        )

    await update.message.reply_text("\n\n".join(lines))


# ── /cancel ───────────────────────────────────────────────────────────────────

async def cmd_cancel_schedule(update: Update, context) -> None:
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /cancel <id>\nGet IDs from /list")
        return
    entry_id = args[0]
    if scheduler_bridge.remove_schedule(entry_id):
        await update.message.reply_text(f"Removed: {entry_id}")
    else:
        await update.message.reply_text(f"Not found: {entry_id}")


# ── /send (structured one-time) ───────────────────────────────────────────────

async def cmd_send(update: Update, context) -> int:
    """
    /send <contact> <YYYY-MM-DD> <HH:MM> <message text...>
    Example: /send Mom 2026-02-26 09:00 Don't forget your medicine
    """
    args = context.args or []
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: /send <contact> <YYYY-MM-DD> <HH:MM> <message>\n"
            "Example: /send Mom 2026-02-26 09:00 Don't forget your medicine"
        )
        return ConversationHandler.END

    contact_name = args[0]
    date_str = args[1]
    time_str = args[2]
    message = ' '.join(args[3:])

    resolved = contacts_mod.resolve(contact_name)
    if not resolved:
        await update.message.reply_text(
            f"Unknown contact: '{contact_name}'\n"
            f"Add with: /contacts add {contact_name} <number>"
        )
        return ConversationHandler.END

    try:
        dt = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
    except ValueError:
        await update.message.reply_text(
            "Invalid date/time. Use YYYY-MM-DD and HH:MM.\n"
            "Example: 2026-02-26 09:00"
        )
        return ConversationHandler.END

    if dt < datetime.now():
        await update.message.reply_text(
            f"That time is in the past: {dt.strftime('%Y-%m-%d %H:%M')}"
        )
        return ConversationHandler.END

    pending = {
        'type': 'once',
        'to': resolved,
        'to_label': contact_name,
        'message': message,
        'dt': dt,
    }
    context.user_data['pending'] = pending
    await update.message.reply_text(_confirmation_text(pending))
    return CONFIRM


# ── /repeat (structured recurring) ───────────────────────────────────────────

async def cmd_repeat(update: Update, context) -> int:
    """
    /repeat <contact> <min> <hour> <dom> <month> <dow> <message text...>
    Example: /repeat Dad 0 8 * * 1 Weekly call reminder
    """
    raw = update.message.text
    parts = raw.split(None, 8)  # /repeat contact m h dom mon dow message
    if len(parts) < 8:
        await update.message.reply_text(
            "Usage: /repeat <contact> <min> <hour> <day> <month> <weekday> <message>\n"
            "Example: /repeat Mom 0 9 * * 1 Good morning!\n"
            "  (weekday: 0=Sun, 1=Mon … 6=Sat)"
        )
        return ConversationHandler.END

    contact_name = parts[1]
    cron_expr = ' '.join(parts[2:7])
    message = parts[7]

    resolved = contacts_mod.resolve(contact_name)
    if not resolved:
        await update.message.reply_text(
            f"Unknown contact: '{contact_name}'\n"
            f"Add with: /contacts add {contact_name} <number>"
        )
        return ConversationHandler.END

    cron_parts = cron_expr.strip().split()
    if len(cron_parts) != 5:
        await update.message.reply_text(
            f"Invalid cron expression: '{cron_expr}'\n"
            "Needs exactly 5 fields: minute hour day-of-month month day-of-week"
        )
        return ConversationHandler.END

    pending = {
        'type': 'recurring',
        'to': resolved,
        'to_label': contact_name,
        'message': message,
        'cron': cron_expr,
    }
    context.user_data['pending'] = pending
    await update.message.reply_text(_confirmation_text(pending))
    return CONFIRM


# ── Natural language scheduling ───────────────────────────────────────────────

async def handle_nl(update: Update, context) -> int:
    """Parse a free-text scheduling request via llama3.2."""
    text = update.message.text.strip()
    await update.message.reply_text("Parsing your request…")

    loop = asyncio.get_event_loop()
    try:
        parsed = await loop.run_in_executor(None, nlp.parse, text)
    except Exception as e:
        logger.error(f"NLP executor error: {e}")
        await update.message.reply_text(
            f"Error: {e}\n"
            "Try the structured command:\n"
            "/send <contact> <YYYY-MM-DD> <HH:MM> <message>"
        )
        return ConversationHandler.END

    if not parsed:
        await update.message.reply_text(
            "Couldn't parse that. Try:\n"
            "/send <contact> <YYYY-MM-DD> <HH:MM> <message>\n"
            "Example: /send Mom 2026-02-26 09:00 Take your medicine"
        )
        return ConversationHandler.END

    recipient_name = parsed.get('recipient', '').strip()
    message = parsed.get('message', '').strip()
    schedule_type = parsed.get('type', 'once')
    dt_str = parsed.get('datetime', '')
    cron_expr = parsed.get('cron', '')

    # Resolve contact
    resolved = contacts_mod.resolve(recipient_name)
    if not resolved:
        # Allow raw phone numbers
        clean_num = re.sub(r'[\s+\-()]', '', recipient_name)
        if re.match(r'^\d{10,15}$', clean_num):
            resolved = clean_num
        else:
            await update.message.reply_text(
                f"I understood the recipient as '{recipient_name}' but that's not in your contacts.\n"
                f"Add with: /contacts add {recipient_name} <number>\n"
                "Or rephrase using the exact contact name."
            )
            return ConversationHandler.END

    if not message:
        await update.message.reply_text(
            "I couldn't figure out what message to send. Please be more explicit."
        )
        return ConversationHandler.END

    if schedule_type == 'once':
        if not dt_str:
            await update.message.reply_text(
                "I couldn't figure out when to send it. Please specify a date and time."
            )
            return ConversationHandler.END
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            await update.message.reply_text(
                f"Couldn't parse the time '{dt_str}'.\n"
                f"Try: /send {recipient_name} YYYY-MM-DD HH:MM {message}"
            )
            return ConversationHandler.END
        if dt < datetime.now():
            await update.message.reply_text(
                f"That time is in the past: {dt.strftime('%Y-%m-%d %H:%M')}. "
                "Did you mean a future date?"
            )
            return ConversationHandler.END

        pending = {
            'type': 'once',
            'to': resolved,
            'to_label': recipient_name,
            'message': message,
            'dt': dt,
        }

    else:  # recurring
        if not cron_expr:
            await update.message.reply_text(
                "I understood this as recurring but couldn't determine the cron schedule.\n"
                "Please use /repeat for recurring messages."
            )
            return ConversationHandler.END
        pending = {
            'type': 'recurring',
            'to': resolved,
            'to_label': recipient_name,
            'message': message,
            'cron': cron_expr,
        }

    context.user_data['pending'] = pending
    await update.message.reply_text(_confirmation_text(pending))
    return CONFIRM


# ── Confirm / deny / correct handlers ────────────────────────────────────────

def _try_parse_datetime(text: str) -> datetime | None:
    """Try to parse a freeform date/time correction. Returns None if unrecognised."""
    text = text.strip().lower()
    now = datetime.now()

    # Resolve day-name keywords
    day_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
               'friday': 4, 'saturday': 5, 'sunday': 6}
    for day_name, weekday in day_map.items():
        if text.startswith(day_name):
            days_ahead = (weekday - now.weekday()) % 7 or 7
            base = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0)
            text = text.replace(day_name, '').strip().lstrip('at').strip()
            if not text:
                return base
            # fall through to parse time portion below
            try:
                t = datetime.strptime(text, '%H:%M')
                return base.replace(hour=t.hour, minute=t.minute)
            except ValueError:
                return base

    # "tomorrow" / "today"
    if text.startswith('tomorrow'):
        base = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
        rest = text.replace('tomorrow', '').strip().lstrip('at').strip()
        if rest:
            try:
                t = datetime.strptime(rest, '%H:%M')
                return base.replace(hour=t.hour, minute=t.minute)
            except ValueError:
                pass
        return base
    if text.startswith('today'):
        base = now.replace(second=0)
        rest = text.replace('today', '').strip().lstrip('at').strip()
        if rest:
            try:
                t = datetime.strptime(rest, '%H:%M')
                return base.replace(hour=t.hour, minute=t.minute)
            except ValueError:
                pass
        return base

    # Explicit formats
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d', '%d/%m/%Y %H:%M', '%d/%m/%Y', '%H:%M'):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == '%H:%M':
                # Time-only → use today's date
                return now.replace(hour=parsed.hour, minute=parsed.minute, second=0)
            return parsed
        except ValueError:
            continue
    return None


def _confirmation_text(pending: dict) -> str:
    if pending['type'] == 'once':
        when_str = pending['dt'].strftime('%Y-%m-%d at %H:%M') + " (one-time)"
        hint = "Reply yes, no, or a corrected date/time (e.g. 'tomorrow 14:00')."
    else:
        when_str = f"{pending['cron']} (recurring)"
        hint = "Reply yes to confirm, no to cancel."
    return (
        f"Schedule this?\n\n"
        f"  To: {pending['to_label']} ({pending['to']})\n"
        f"  Message: {pending['message']}\n"
        f"  When: {when_str}\n\n"
        + hint
    )


async def handle_correction(update: Update, context) -> int:
    """Handle a date/time correction during the confirmation step."""
    pending = context.user_data.get('pending')
    if not pending or pending['type'] != 'once':
        # Not a one-time pending — cancel
        context.user_data.pop('pending', None)
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    dt = _try_parse_datetime(update.message.text)
    if dt is None:
        await update.message.reply_text(
            "Couldn't parse that as a date/time.\n"
            "Try: 'tomorrow 14:00', '2026-03-01 09:00', 'friday 18:00', or 'no' to cancel."
        )
        return CONFIRM  # stay in confirm state

    if dt < datetime.now():
        await update.message.reply_text(
            f"That time is in the past ({dt.strftime('%Y-%m-%d %H:%M')}). Try again."
        )
        return CONFIRM

    pending['dt'] = dt
    await update.message.reply_text(_confirmation_text(pending))
    return CONFIRM


async def handle_confirm(update: Update, context) -> int:
    pending = context.user_data.get('pending')
    if not pending:
        await update.message.reply_text("Nothing pending.")
        return ConversationHandler.END

    try:
        if pending['type'] == 'once':
            entry_id = scheduler_bridge.add_schedule(
                to=pending['to'],
                message=pending['message'],
                schedule_type='once',
                dt=pending['dt'],
            )
        else:
            entry_id = scheduler_bridge.add_schedule(
                to=pending['to'],
                message=pending['message'],
                schedule_type='recurring',
                cron_expr=pending['cron'],
            )
        context.user_data.pop('pending', None)
        await update.message.reply_text(f"Scheduled. ID: {entry_id}")
    except Exception as e:
        logger.error(f"Failed to add schedule: {e}")
        await update.message.reply_text(f"Failed to schedule: {e}")

    return ConversationHandler.END


async def handle_deny(update: Update, context) -> int:
    context.user_data.pop('pending', None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ['TELEGRAM_BOT_TOKEN']
    allowed_user_id = int(os.environ['ALLOWED_USER_ID'])

    app = Application.builder().token(token).build()
    auth = filters.User(user_id=allowed_user_id)

    # Confirmation conversation handler
    # Note: all other messages during CONFIRM state → denied (ends conversation)
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('send', cmd_send, filters=auth),
            CommandHandler('repeat', cmd_repeat, filters=auth),
            MessageHandler(filters.TEXT & ~filters.COMMAND & auth, handle_nl),
        ],
        states={
            CONFIRM: [
                MessageHandler(filters.Regex(r'(?i)^yes$') & auth, handle_confirm),
                MessageHandler(filters.Regex(r'(?i)^no$') & auth, handle_deny),
                MessageHandler(filters.TEXT & ~filters.COMMAND & auth, handle_correction),
            ],
        },
        fallbacks=[
            MessageHandler(filters.ALL & auth, handle_deny),
        ],
        conversation_timeout=120,
    )

    # Register conv FIRST so it intercepts /send and /repeat as entry points,
    # and handles the CONFIRM state. Other commands are registered after
    # (they'll only fire when the user is not in an active conversation).
    app.add_handler(conv)
    app.add_handler(CommandHandler('start', cmd_start, filters=auth))
    app.add_handler(CommandHandler('contacts', cmd_contacts, filters=auth))
    app.add_handler(CommandHandler('list', cmd_list, filters=auth))
    app.add_handler(CommandHandler('cancel', cmd_cancel_schedule, filters=auth))

    logger.info("WhatsApp Telegram Bridge starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
