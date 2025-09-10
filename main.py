import logging
import os
import json
import re
import datetime
from dotenv import load_dotenv

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

# --- Setup ---
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required.")

# --- Globals & Data Persistence ---
COMMAND_FILE = "user_commands.json"
user_commands = {}

# Conversation states
COMMAND, REPLY = range(2)
CONFIRM_DELETE = range(1)

# --- Helper Functions ---

def load_user_commands():
    """Loads custom commands from the JSON file into memory."""
    global user_commands
    try:
        with open(COMMAND_FILE, "r") as f:
            user_commands = json.load(f)
        logger.info(f"Loaded {len(user_commands)} commands from {COMMAND_FILE}")
    except FileNotFoundError:
        logger.info(f"{COMMAND_FILE} not found. Starting fresh.")
        user_commands = {}
    except json.JSONDecodeError:
        logger.error(f"Error decoding {COMMAND_FILE}. Starting fresh.")
        user_commands = {}

def save_user_commands():
    """Saves the current custom commands to the JSON file."""
    with open(COMMAND_FILE, "w") as f:
        json.dump(user_commands, f, indent=4)

def parse_duration(duration_str: str) -> datetime.timedelta:
    """Parses a duration string like '5m', '1h', '2d' into a timedelta."""
    unit = duration_str[-1].lower()
    value = int(duration_str[:-1])
    if unit == 'm':
        return datetime.timedelta(minutes=value)
    elif unit == 'h':
        return datetime.timedelta(hours=value)
    elif unit == 'd':
        return datetime.timedelta(days=value)
    else:
        raise ValueError("Invalid duration unit. Use 'm', 'h', or 'd'.")

# --- Core Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a detailed welcome and help message."""
    help_text = (
        "Hello! I'm your friendly bot. Here's what I can do:\n\n"
        "**Custom Commands**\n"
        "/new - Create a new custom command.\n"
        "/commandlist - View all custom commands.\n"
        "/deleteall - Delete all custom commands.\n\n"
        "**User Management**\n"
        "/userinfo <user_id> - Get info about a user.\n"
        "/removeuser <user_id> - Kick a user (they can rejoin).\n\n"
        "**Moderator Commands**\n"
        "/ban <user_id> [reason] - Ban a user permanently.\n"
        "/unban <user_id> - Unban a user.\n"
        "/mute <user_id> <5m|1h|2d> - Mute a user for a duration.\n"
        "/unmute <user_id> - Unmute a user.\n\n"
        "**Chat Management**\n"
        "/pin - Reply to a message to pin it.\n"
        "/invitelink - Get a new invite link for this chat."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# --- Custom Command Management ---

async def new_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the /new command conversation."""
    await update.message.reply_text("What is the command name? (e.g., 'hello' for /hello)")
    return COMMAND

async def get_command_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets and validates the new command name."""
    command_name = re.sub(r'[\s-]+', '_', update.message.text.lower().strip().lstrip('/'))
    if not command_name.isalnum() and '_' not in command_name:
        await update.message.reply_text("Invalid command name. Use letters, numbers, and underscores. Try again.")
        return COMMAND
    if command_name in user_commands:
        await update.message.reply_text("That command already exists. Try another name.")
        return COMMAND
    context.user_data['new_command_name'] = command_name
    await update.message.reply_text(f"Great! The command will be /{command_name}.\n\nNow, what should I reply with?")
    return REPLY

async def get_command_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new command and adds its handler."""
    command_name = context.user_data['new_command_name']
    reply_text = update.message.text
    user_commands[command_name] = reply_text
    save_user_commands()
    context.application.add_handler(CommandHandler(command_name, generic_command_handler))
    await update.message.reply_text(f"✅ Success! The command /{command_name} has been created.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels any active conversation."""
    await update.message.reply_text("Operation canceled.")
    context.user_data.clear()
    return ConversationHandler.END

async def command_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays all saved custom commands."""
    if not user_commands:
        await update.message.reply_text("No custom commands saved yet. Use /new to create one!")
        return
    message = "Available custom commands:\n\n" + "\n".join(f"/{cmd}" for cmd in sorted(user_commands.keys()))
    await update.message.reply_text(message)

async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all dynamically created user commands."""
    command = update.message.text[1:].split('@')[0]
    if command in user_commands:
        await update.message.reply_text(user_commands[command])

async def delete_all_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the process to delete all custom commands."""
    if not user_commands:
        await update.message.reply_text("There are no custom commands to delete.")
        return ConversationHandler.END
    await update.message.reply_text("⚠️ Are you sure you want to delete ALL custom commands? This cannot be undone. Reply 'yes' to confirm.")
    return CONFIRM_DELETE

async def delete_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Deletes all commands if confirmation is received."""
    if update.message.text.lower() == 'yes':
        commands_to_remove = list(user_commands.keys())
        # The handlers are in a list at application.handlers[0]
        current_handlers = context.application.handlers[0]
        # Filter out the handlers that match our custom commands
        context.application.handlers[0] = [
            h for h in current_handlers
            if not (isinstance(h, CommandHandler) and any(cmd in commands_to_remove for cmd in h.commands))
        ]
        user_commands.clear()
        save_user_commands()
        await update.message.reply_text("✅ All custom commands have been deleted.")
    else:
        await update.message.reply_text("Deletion canceled.")
    return ConversationHandler.END

# --- User Management & Moderator Commands ---

async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets info about a user."""
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    try:
        user_id = int(context.args[0])
        user = await context.bot.get_chat(user_id)
        message = (
            f"User Info:\n"
            f"ID: `{user.id}`\n"
            f"First Name: `{user.first_name}`\n"
            f"Last Name: `{user.last_name or 'N/A'}`\n"
            f"Username: `@{user.username or 'N/A'}`"
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID.")
    except Exception as e:
        logger.error(f"Error in /userinfo: {e}")
        await update.message.reply_text(f"Could not find user with ID: {context.args[0]}.")

async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kicks a user from the chat."""
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
        await update.message.reply_text(f"User {user_id} has been removed.")
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID.")
    except Exception as e:
        logger.error(f"Error in /removeuser: {e}")
        await update.message.reply_text("Failed to remove user. Do I have admin rights?")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bans a user from the chat."""
    # Bot must be an admin with "Ban users" rights
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id> [reason]")
        return
    try:
        user_id = int(context.args[0])
        reason = " ".join(context.args[1:]) or "No reason provided."
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
        await update.message.reply_text(f"Banned user {user_id}. Reason: {reason}")
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID.")
    except Exception as e:
        logger.error(f"Error in /ban: {e}")
        await update.message.reply_text("Failed to ban user. Do I have admin rights?")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unbans a user."""
    # Bot must be an admin with "Ban users" rights
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=user_id)
        await update.message.reply_text(f"Unbanned user {user_id}.")
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID.")
    except Exception as e:
        logger.error(f"Error in /unban: {e}")
        await update.message.reply_text("Failed to unban user. Do I have admin rights?")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mutes a user for a specified duration."""
    # Bot must be an admin with "Restrict users" rights
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /mute <user_id> <duration> (e.g., 5m, 1h, 2d)")
        return
    try:
        user_id = int(context.args[0])
        duration = parse_duration(context.args[1])
        until_date = datetime.datetime.now() + duration
        permissions = ChatPermissions(can_send_messages=False)
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date
        )
        await update.message.reply_text(f"Muted user {user_id} for {context.args[1]}.")
    except ValueError as e:
        await update.message.reply_text(str(e))
    except Exception as e:
        logger.error(f"Error in /mute: {e}")
        await update.message.reply_text("Failed to mute user. Do I have admin rights?")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmutes a user."""
    # Bot must be an admin with "Restrict users" rights
    if not context.args:
        await update.message.reply_text("Usage: /unmute <user_id>")
        return
    try:
        user_id = int(context.args[0])
        permissions = ChatPermissions(
            can_send_messages=True, can_send_media_messages=True, 
            can_send_polls=True, can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=permissions
        )
        await update.message.reply_text(f"Unmuted user {user_id}.")
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID.")
    except Exception as e:
        logger.error(f"Error in /unmute: {e}")
        await update.message.reply_text("Failed to unmute user. Do I have admin rights?")

# --- Chat Management Commands ---

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pins the message the user is replying to."""
    # Bot must be an admin with "Pin messages" rights
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message with /pin to pin it.")
        return
    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.reply_to_message.message_id
        )
    except Exception as e:
        logger.error(f"Error in /pin: {e}")
        await update.message.reply_text("Failed to pin message. Do I have admin rights?")

async def invitelink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates a new chat invite link."""
    # Bot must be an admin with "Invite users" rights
    try:
        link = await context.bot.export_chat_invite_link(chat_id=update.effective_chat.id)
        await update.message.reply_text(f"Here is a new invite link: {link}")
    except Exception as e:
        logger.error(f"Error in /invitelink: {e}")
        await update.message.reply_text("Failed to create invite link. Do I have admin rights?")

# --- Main Bot Logic ---

def main() -> None:
    """Start the bot."""
    load_user_commands()
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    new_command_conv = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={
            COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_name)],
            REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_reply)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    delete_all_conv = ConversationHandler(
        entry_points=[CommandHandler("deleteall", delete_all_start)],
        states={
            CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_all_confirm)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(new_command_conv)
    application.add_handler(delete_all_conv)

    # Add all other handlers
    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("commandlist", command_list_command),
        CommandHandler("userinfo", user_info_command),
        CommandHandler("removeuser", remove_user_command),
        CommandHandler("ban", ban_command),
        CommandHandler("unban", unban_command),
        CommandHandler("mute", mute_command),
        CommandHandler("unmute", unmute_command),
        CommandHandler("pin", pin_command),
        CommandHandler("invitelink", invitelink_command),
    ]
    application.add_handlers(handlers)

    # Add handlers for all loaded custom commands
    for command in user_commands:
        application.add_handler(CommandHandler(command, generic_command_handler))

    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()