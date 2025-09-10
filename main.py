import json
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# States for ConversationHandler
WAITING_FOR_COMMAND, WAITING_FOR_RESPONSE = range(2)

# File to store new commands
COMMANDS_FILE = "user_commands.json"

# Load existing commands
try:
    with open(COMMANDS_FILE, "r") as f:
        user_commands = json.load(f)
except FileNotFoundError:
    user_commands = {}

# /new command start
async def new_command_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello. What new command would you like to add?")
    return WAITING_FOR_COMMAND

# Capture the new command
async def receive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command_text = update.message.text.strip()
    # Replace spaces with dashes
    command_text = command_text.replace(" ", "-")
    
    # Ensure it starts with /
    if not command_text.startswith("/"):
        command_text = "/" + command_text

    context.user_data["new_command_name"] = command_text
    await update.message.reply_text(f"Alright, the command {command_text} was saved. What would you like me to reply with when this command is used?")
    return WAITING_FOR_RESPONSE

# Capture the response for the new command
async def receive_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response_text = update.message.text
    command_name = context.user_data["new_command_name"]

    # Save in dictionary and file
    user_commands[command_name] = response_text
    with open(COMMANDS_FILE, "w") as f:
        json.dump(user_commands, f, indent=4)

    # Dynamically add handler for the new command
    async def dynamic_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(response_text)

    context.application.add_handler(CommandHandler(command_name[1:], dynamic_reply))
    
    await update.message.reply_text(f"Command {command_name} is now ready to use!")
    return ConversationHandler.END

# Cancel handler
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Command creation cancelled.")
    return ConversationHandler.END

# Load saved commands when bot starts
def load_saved_commands(application):
    for cmd, reply in user_commands.items():
        async def dynamic_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, reply_text=reply):
            await update.message.reply_text(reply_text)
        application.add_handler(CommandHandler(cmd[1:], dynamic_reply))

if __name__ == "__main__":
    app = ApplicationBuilder().token("BOT_TOKEN").build()

    # Conversation for /new
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new", new_command_start)],
        states={
            WAITING_FOR_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_command)],
            WAITING_FOR_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_response)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    # Load previously saved commands
    load_saved_commands(app)

    app.run_polling()