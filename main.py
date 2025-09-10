import logging
import os
import json
import re
from dotenv import load_dotenv

import google.generativeai as genai
from telegram import Update
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
# Load environment variables from .env file for local development
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get API keys from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("BOT_TOKEN and GEMINI_API_KEY environment variables are required.")

# Configure the Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')

# --- Globals & Data Persistence ---
COMMAND_FILE = "user_commands.json"

# In-memory storage for AI chat history {chat_id: [history]}
gemini_memory = {}
# In-memory storage for custom commands {command_name: reply_text}
user_commands = {}

# Conversation states for /new command
COMMAND, REPLY = range(2)

# --- Helper Functions ---

def load_user_commands():
    """Loads custom commands from the JSON file into memory."""
    global user_commands
    try:
        with open(COMMAND_FILE, "r") as f:
            user_commands = json.load(f)
        logger.info(f"Loaded {len(user_commands)} commands from {COMMAND_FILE}")
    except FileNotFoundError:
        logger.info(f"{COMMAND_FILE} not found. Starting with an empty command list.")
        user_commands = {}
    except json.JSONDecodeError:
        logger.error(f"Error decoding {COMMAND_FILE}. Starting fresh.")
        user_commands = {}

def save_user_commands():
    """Saves the current custom commands from memory to the JSON file."""
    with open(COMMAND_FILE, "w") as f:
        json.dump(user_commands, f, indent=4)

async def split_and_send_message(update: Update, text: str, parse_mode: str = None):
    """Splits a long message into multiple parts and sends them."""
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        try:
            await update.message.reply_text(text, parse_mode=parse_mode)
        except Exception as e:
            logger.warning(f"Failed to send with parse_mode={parse_mode}: {e}. Sending as plain text.")
            await update.message.reply_text(text)
        return

    parts = []
    while len(text) > 0:
        if len(text) > MAX_LENGTH:
            part = text[:MAX_LENGTH]
            # Try to find a good split point (newline, then space)
            last_newline = part.rfind('\n')
            last_space = part.rfind(' ')
            if last_newline > 0:
                split_at = last_newline
            elif last_space > 0:
                split_at = last_space
            else:
                split_at = MAX_LENGTH

            parts.append(text[:split_at])
            text = text[split_at:].lstrip()
        else:
            parts.append(text)
            break

    for part in parts:
        try:
            await update.message.reply_text(part, parse_mode=parse_mode)
        except Exception as e:
            logger.warning(f"Failed to send part with parse_mode={parse_mode}: {e}. Sending as plain text.")
            await update.message.reply_text(part)

# --- Core Bot Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Hello! I'm a bot powered by Google Gemini.\n\n"
        "Here are some commands you can use:\n"
        "/gemini <text> - Chat with the AI.\n"
        "/new_gemini - Start a new AI conversation.\n"
        "/new - Create a new custom command.\n"
        "/commandlist - View all custom commands.\n"
        "/userinfo <user_id> - Get info about a user.\n"
        "/removeuser <user_id> - Remove a user from the chat."
    )

async def gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /gemini command to chat with the AI."""
    chat_id = update.effective_chat.id
    user_text = " ".join(context.args)

    if not user_text:
        await update.message.reply_text("Please provide some text after the /gemini command.")
        return

    # Initialize memory for the chat if it doesn't exist
    if chat_id not in gemini_memory:
        gemini_memory[chat_id] = gemini_model.start_chat(history=[])

    try:
        # Show a "thinking..." message
        thinking_message = await update.message.reply_text("🤔 Thinking...")

        response = gemini_memory[chat_id].send_message(user_text)

        # Edit the message to show the final response
        await context.bot.delete_message(chat_id=chat_id, message_id=thinking_message.message_id)
        await split_and_send_message(update, response.text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        await update.message.reply_text("Sorry, I encountered an error while talking to the AI.")

async def new_gemini_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resets the Gemini AI conversation history for the chat."""
    chat_id = update.effective_chat.id
    if chat_id in gemini_memory:
        del gemini_memory[chat_id]
    await update.message.reply_text("🤖 AI memory for this chat has been reset. Let's start a new conversation!")

# --- Custom Command Management ---

async def new_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to create a new command."""
    await update.message.reply_text(
        "Let's create a new command.\n"
        "First, what is the command name? (e.g., 'hello' for /hello)"
    )
    return COMMAND

async def get_command_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the command name, sanitizes it, and asks for the reply."""
    command_name = update.message.text.lower().strip()

    # Sanitize: remove leading '/' and replace spaces/hyphens with underscores
    command_name = re.sub(r'[\s-]+', '_', command_name)
    if command_name.startswith('/'):
        command_name = command_name[1:]

    if not command_name.isalnum() and '_' not in command_name:
        await update.message.reply_text("Invalid command name. Please use only letters, numbers, and underscores. Let's try again.")
        return COMMAND

    if command_name in user_commands:
        await update.message.reply_text("That command already exists. Please choose another name.")
        return COMMAND

    context.user_data['new_command_name'] = command_name
    await update.message.reply_text(f"Great! The command will be /{command_name}.\n\nNow, what should I reply with when this command is used?")
    return REPLY

async def get_command_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the reply text, saves the new command, and adds the handler."""
    command_name = context.user_data['new_command_name']
    reply_text = update.message.text

    user_commands[command_name] = reply_text
    save_user_commands()

    # Dynamically add the new command handler to the running bot
    new_handler = CommandHandler(command_name, generic_command_handler)
    context.application.add_handler(new_handler)

    await update.message.reply_text(f"✅ Success! The command /{command_name} has been created.")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the new command creation process."""
    await update.message.reply_text("Command creation canceled.")
    context.user_data.clear()
    return ConversationHandler.END

async def command_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a list of all saved custom commands."""
    if not user_commands:
        await update.message.reply_text("There are no custom commands saved yet. Use /new to create one!")
        return

    message = "Here are the available custom commands:\n\n"
    for command in sorted(user_commands.keys()):
        message += f"/{command}\n"

    await update.message.reply_text(message)

async def generic_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all dynamically created user commands."""
    command = update.message.text[1:].split(' ')[0] # Extract command from /command@botname
    if command in user_commands:
        await update.message.reply_text(user_commands[command])

# --- User Management Commands ---

async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets information about a Telegram user by their ID."""
    if not context.args:
        await update.message.reply_text("Please provide a user ID. Usage: /userinfo <user_id>")
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
        await update.message.reply_text("Invalid User ID format. Please provide a valid number.")
    except Exception as e:
        logger.error(f"Error in /userinfo: {e}")
        await update.message.reply_text(f"Could not find user with ID: {context.args[0]}.")


async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes a user from the chat. Bot must be an admin."""
    # NOTE: Making this command public is risky in a group with multiple members.
    # The bot must have "Ban users" permission to execute this.
    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text("Please provide a user ID. Usage: /removeuser <user_id>")
        return

    try:
        user_id = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=user_id) # Unban to allow re-entry
        await update.message.reply_text(f"User {user_id} has been removed from the chat.")
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid User ID format. Please provide a valid number.")
    except Exception as e:
        logger.error(f"Error in /removeuser: {e}")
        await update.message.reply_text(f"Failed to remove user. I might not have admin rights, or the user ID is incorrect.")

# --- Main Bot Logic ---

def main() -> None:
    """Start the bot."""
    # Load commands from file at startup
    load_user_commands()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Register Handlers ---

    # Conversation handler for the /new command
    new_command_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={
            COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_name)],
            REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_command_reply)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    application.add_handler(new_command_handler)

    # Standard command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("gemini", gemini_command))
    application.add_handler(CommandHandler("new_gemini", new_gemini_command))
    application.add_handler(CommandHandler("commandlist", command_list_command))
    application.add_handler(CommandHandler("userinfo", user_info_command))
    application.add_handler(CommandHandler("removeuser", remove_user_command))

    # Add handlers for all loaded custom commands
    for command in user_commands:
        application.add_handler(CommandHandler(command, generic_command_handler))

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    main()