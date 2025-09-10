import os
import json
from telegram import Update, User
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from google.genai import ChatModel, InputText
from dotenv import load_dotenv

# Load .env if running locally (optional)
load_dotenv()

# ===== Environment Variables =====
TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set!")

# ===== Admin Settings =====
ADMINS = [123456789]  # Replace with your Telegram user ID

# ===== Conversation States =====
WAITING_FOR_COMMAND, WAITING_FOR_RESPONSE = range(2)

# ===== Load or Initialize Commands File =====
COMMANDS_FILE = "user_commands.json"
try:
    with open(COMMANDS_FILE, "r") as f:
        user_commands = json.load(f)
except FileNotFoundError:
    user_commands = {}

# ===== Gemini AI Setup =====
chat_model = ChatModel(api_key=GEMINI_API_KEY)

# ===== Helper Functions =====
def admin_only(func):
    """Decorator to restrict admin commands."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMINS:
            await update.message.reply_text("❌ You are not allowed to use this command.")
            return
        return await func(update, context)
    return wrapper

def save_commands():
    """Save commands to file."""
    with open(COMMANDS_FILE, "w") as f:
        json.dump(user_commands, f, indent=4)

def load_saved_commands(application):
    """Load previously saved commands dynamically."""
    for cmd, reply in user_commands.items():
        async def dynamic_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_text=reply):
            await update.message.reply_text(reply_text)
        application.add_handler(CommandHandler(cmd[1:], dynamic_reply))

# ===== /new Command =====
async def new_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello. What new command would you like to add?")
    return WAITING_FOR_COMMAND

async def receive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command_text = update.message.text.strip().replace(" ", "-")
    if not command_text.startswith("/"):
        command_text = "/" + command_text
    context.user_data["new_command_name"] = command_text
    await update.message.reply_text(
        f"Alright, the command {command_text} was saved.\n"
        "What should the bot reply when this command is used?"
    )
    return WAITING_FOR_RESPONSE

async def receive_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response_text = update.message.text
    command_name = context.user_data["new_command_name"]

    # Save command
    user_commands[command_name] = response_text
    save_commands()

    # Add handler dynamically
    async def dynamic_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_text=response_text):
        await update.message.reply_text(reply_text)

    context.application.add_handler(CommandHandler(command_name[1:], dynamic_reply))
    await update.message.reply_text(f"Command {command_name} is now ready to use!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Command creation cancelled.")
    return ConversationHandler.END

# ===== Admin Commands =====
@admin_only
async def command_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_commands:
        await update.message.reply_text("No commands saved yet.")
        return
    cmds = "\n".join(user_commands.keys())
    await update.message.reply_text(f"Saved commands:\n{cmds}")

@admin_only
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <user_id>")
        return
    user_id = int(context.args[0])
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"User {user_id} removed from the chat.")
    except Exception as e:
        await update.message.reply_text(f"Failed to remove user: {e}")

@admin_only
async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    user_id = int(context.args[0])
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        u: User = member.user
        info = f"ID: {u.id}\nName: {u.full_name}\nUsername: @{u.username}\nIs bot: {u.is_bot}"
        await update.message.reply_text(info)
    except Exception as e:
        await update.message.reply_text(f"Failed to get user info: {e}")

# ===== /gemini AI Command =====
async def gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)
    if not question:
        await update.message.reply_text("Please ask a question after /gemini")
        return
    try:
        input_text = InputText(text=question)
        response = chat_model.chat(input_text=input_text)
        await update.message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text(f"Error contacting Gemini: {e}")

# ===== Main Bot Setup =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Dynamic user commands
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={
            WAITING_FOR_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_command)],
            WAITING_FOR_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_response)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    # Admin commands
    app.add_handler(CommandHandler("commandlist", command_list))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(CommandHandler("userinfo", user_info))

    # AI command
    app.add_handler(CommandHandler("gemini", gemini))

    # Load saved commands
    load_saved_commands(app)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()