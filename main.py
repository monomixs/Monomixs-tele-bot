import os
import json
from telegram import Update, User
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode
from google import genai
from dotenv import load_dotenv

# ===== Load Environment =====
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set!")

# ===== Conversation States =====
WAITING_FOR_COMMAND, WAITING_FOR_RESPONSE = range(2)

# ===== User commands storage =====
COMMANDS_FILE = "user_commands.json"
try:
    with open(COMMANDS_FILE, "r") as f:
        user_commands = json.load(f)
except FileNotFoundError:
    user_commands = {}

# ===== Gemini Client & Memory =====
client = genai.Client(api_key=GEMINI_API_KEY)
gemini_memory = {}  # chat_id -> list of messages

# ===== Helper Functions =====
def save_commands():
    with open(COMMANDS_FILE, "w") as f:
        json.dump(user_commands, f, indent=4)

def load_saved_commands(application):
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

    user_commands[command_name] = response_text
    save_commands()

    async def dynamic_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_text=response_text):
        await update.message.reply_text(reply_text)

    context.application.add_handler(CommandHandler(command_name[1:], dynamic_reply))
    await update.message.reply_text(f"Command {command_name} is now ready to use!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Command creation cancelled.")
    return ConversationHandler.END

# ===== Public “Admin” Commands =====
async def command_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_commands:
        await update.message.reply_text("No commands saved yet.")
        return
    cmds = "\n".join(user_commands.keys())
    await update.message.reply_text(f"Saved commands:\n{cmds}")

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

# ===== /gemini AI Command with Memory & Markdown =====
async def gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    question = " ".join(context.args)
    if not question:
        await update.message.reply_text("Please ask something after /gemini")
        return

    if chat_id not in gemini_memory:
        gemini_memory[chat_id] = []

    gemini_memory[chat_id].append({"role": "user", "content": question})

    memory_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in gemini_memory[chat_id]])
    prompt = f"{memory_text}\nassistant:"

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        gemini_memory[chat_id].append({"role": "assistant", "content": response.text})
        await update.message.reply_text(
            response.text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"Error contacting Gemini: {e}")

# ===== /new_gemini Command to Reset Memory =====
async def new_gemini(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    gemini_memory[chat_id] = []
    await update.message.reply_text("Gemini memory has been reset. Starting a new chat.")

# ===== Main Bot Setup =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # /new command conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={
            WAITING_FOR_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_command)],
            WAITING_FOR_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_response)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    # Public commands
    app.add_handler(CommandHandler("commandlist", command_list))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(CommandHandler("userinfo", user_info))

    # Gemini AI commands
    app.add_handler(CommandHandler("gemini", gemini))
    app.add_handler(CommandHandler("new_gemini", new_gemini))

    # Load saved user commands
    load_saved_commands(app)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()