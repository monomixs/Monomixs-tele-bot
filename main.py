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
# New structure to hold commands scoped to groups and users
all_commands = {"groups": {}, "users": {}}

PREMADE_COMMANDS = {
    "start": "Shows this help message.",
    "new": "Create a new custom command for this chat.",
    "commandlist": "Lists all available commands for this chat.",
    "deleteall": "Delete all custom commands from this chat.",
    "userinfo": "<user_id> - Get info about a user.",
    "removeuser": "<user_id> - Kick a user (they can rejoin).",
    "ban": "<user_id> [reason] - Ban a user permanently.",
    "unban": "<user_id> - Unban a user.",
    "mute": "<user_id> <5m|1h|2d> - Mute a user for a duration.",
    "unmute": "<user_id> - Unmute a user.",
    "pin": "Reply to a message to pin it.",
    "invitelink": "Get a new invite link for this chat.",
}

# Conversation states
COMMAND, REPLY = range(2)
CONFIRM_DELETE = range(1)

# --- Helper Functions ---

def load_user_commands():
    """Loads the new scoped command structure from the JSON file."""
    global all_commands
    try:
        with open(COMMAND_FILE, "r") as f:
            data = json.load(f)
            # Ensure the base keys exist
            all_commands["groups"] = data.get("groups", {})
            all_commands["users"] = data.get("users", {})
        logger.info(f"Loaded commands for {len(all_commands['groups'])} groups and {len(all_commands['users'])} users.")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.info(f"{COMMAND_FILE} not found or invalid. Starting fresh.")
        all_commands = {"groups": {}, "users": {}}

def save_user_commands():
    """Saves the scoped command structure to the JSON file."""
    with open(COMMAND_FILE, "w") as f:
        json.dump(all_commands, f, indent=4)

def parse_duration(duration_str: str) -> datetime.timedelta:
    if not duration_str[:-1].isdigit(): raise ValueError("Invalid number.")
    unit = duration_str[-1].lower()
    value = int(duration_str[:-1])
    if unit == 'm': return datetime.timedelta(minutes=value)
    if unit == 'h': return datetime.timedelta(hours=value)
    if unit == 'd': return datetime.timedelta(days=value)
    raise ValueError("Invalid duration unit. Use 'm', 'h', or 'd'.")

# --- Core Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = "Hello! I'm your friendly bot. Here's a list of my built-in commands:\n\n"
    for command, description in PREMADE_COMMANDS.items():
        message += f"/{command} - {description}\n\n"  # <-- double newline for spacing
    message += "Custom commands are specific to each chat. Use /commandlist to see them."
    await update.message.reply_text(message)

async def command_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a unified list of all commands, specific to the chat context."""
    chat_id = str(update.effective_chat.id)
    chat_type = update.effective_chat.type

    message = "--- Built-in Commands ---\n\n"
    for command, description in PREMADE_COMMANDS.items():
        message += f"/{command} - {description}\n\n"  # <-- double newline

    message += "--- Custom Commands for this Chat ---\n\n"
    
    custom_commands_for_chat = {}
    if chat_type in ["group", "supergroup"]:
        custom_commands_for_chat = all_commands["groups"].get(chat_id, {})
    elif chat_type == "private":
        custom_commands_for_chat = all_commands["users"].get(chat_id, {})

    if not custom_commands_for_chat:
        message += "There are no custom commands for this chat yet. Use /new to create one!"
    else:
        for command in sorted(custom_commands_for_chat.keys()):
            message += f"/{command}\n\n"  # <-- double newline for spacing
            
    await update.message.reply_text(message)

# --- Custom Command Management (Now Context-Aware) ---

async def new_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Let's create a new command for this chat.\nWhat is the command name? (e.g., 'hello')")
    return COMMAND

async def get_command_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets and validates the new command name within the chat's context."""
    chat_id = str(update.effective_chat.id)
    chat_type = update.effective_chat.type
    
    command_name = re.sub(r'[\s-]+', '_', update.message.text.lower().strip().lstrip('/'))

    if not command_name or not (command_name.isalnum() or '_' in command_name):
        await update.message.reply_text("Invalid name. Use only letters, numbers, and underscores.")
        return COMMAND
        
    if command_name in PREMADE_COMMANDS:
        await update.message.reply_text("That is a built-in command. Please choose another name.")
        return COMMAND

    if chat_type in ["group", "supergroup"]:
        if command_name in all_commands["groups"].get(chat_id, {}):
            await update.message.reply_text("That command already exists in this group. Try another.")
            return COMMAND
    elif chat_type == "private":
        if command_name in all_commands["users"].get(chat_id, {}):
            await update.message.reply_text("That command already exists for you. Try another.")
            return COMMAND

    context.user_data['new_command_name'] = command_name
    await update.message.reply_text(f"Great! The command will be /{command_name}.\n\nNow, what should I reply with?")
    return REPLY

async def get_command_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new command to the correct scope (group or user)."""
    chat_id = str(update.effective_chat.id)
    chat_type = update.effective_chat.type
    command_name = context.user_data['new_command_name']
    reply_text = update.message.text

    if chat_type in ["group", "supergroup"]:
        if chat_id not in all_commands["groups"]:
            all_commands["groups"][chat_id] = {}
        all_commands["groups"][chat_id][command_name] = reply_text
    elif chat_type == "private":
        if chat_id not in all_commands["users"]:
            all_commands["users"][chat_id] = {}
        all_commands["users"][chat_id][command_name] = reply_text
    
    save_user_commands()
    await update.message.reply_text(f"✅ Success! The command /{command_name} has been created for this chat.")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation canceled.")
    context.user_data.clear()
    return ConversationHandler.END

async def handle_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.message.text[1:].split('@')[0].lower()
    chat_id = str(update.effective_chat.id)
    chat_type = update.effective_chat.type
    
    response = None
    if chat_type in ["group", "supergroup"]:
        response = all_commands["groups"].get(chat_id, {}).get(command)
    elif chat_type == "private":
        response = all_commands["users"].get(chat_id, {}).get(command)
        
    if response:
        await update.message.reply_text(response)

async def delete_all_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("⚠️ Are you sure you want to delete ALL custom commands from this chat? This cannot be undone. Reply 'yes' to confirm.")
    return CONFIRM_DELETE

async def delete_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.lower() == 'yes':
        chat_id = str(update.effective_chat.id)
        chat_type = update.effective_chat.type
        
        deleted = False
        if chat_type in ["group", "supergroup"] and chat_id in all_commands["groups"]:
            del all_commands["groups"][chat_id]
            deleted = True
        elif chat_type == "private" and chat_id in all_commands["users"]:
            del all_commands["users"][chat_id]
            deleted = True

        if deleted:
            save_user_commands()
            await update.message.reply_text("✅ All custom commands for this chat have been deleted.")
        else:
            await update.message.reply_text("There were no custom commands in this chat to delete.")
    else:
        await update.message.reply_text("Deletion canceled.")
    return ConversationHandler.END

# --- User Management & Moderator Commands (unchanged) ---
# [Keep all your existing user/moderator commands here without change]

# --- Main Bot Logic ---

def main() -> None:
    load_user_commands()
    application = Application.builder().token(BOT_TOKEN).build()

    new_command_conv = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_name)], REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_reply)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    delete_all_conv = ConversationHandler(
        entry_points=[CommandHandler("deleteall", delete_all_start)],
        states={CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_all_confirm)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(new_command_conv)
    application.add_handler(delete_all_conv)

    for command, handler_func in {
        "start": start_command, "commandlist": command_list_command, "userinfo": user_info_command,
        "removeuser": remove_user_command, "ban": ban_command, "unban": unban_command,
        "mute": mute_command, "unmute": unmute_command, "pin": pin_command, "invitelink": invitelink_command
    }.items():
        application.add_handler(CommandHandler(command, handler_func))

    application.add_handler(MessageHandler(filters.COMMAND & (~filters.UpdateType.EDITED), handle_custom_command), group=1)

    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()