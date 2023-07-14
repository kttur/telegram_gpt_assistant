import os
import sqlite3

import openai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler


class SQLiteRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS messages "
            "(user_id INT, chat_id TEXT, role TEXT, message TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS users "
            "(user_id INT, chat_id TEXT)"
        )
        self.conn.commit()

    def add_message(self, user_id: int, role: str, message: str):
        self.cursor.execute(
            "INSERT INTO messages (user_id, chat_id, role, message) "
            "VALUES (?, 0, ?, ?)",
            (user_id, role, message)
        )
        self.conn.commit()

    def get_messages(self, user_id: int, limit: int = 20) -> list[dict]:
        self.cursor.execute("""
            SELECT role, message, timestamp
            FROM messages
            WHERE user_id = ?
            AND chat_id = 0
            ORDER BY timestamp DESC LIMIT ?""",
            (user_id, limit)
        )
        result = [
            {
                "role": "system",
                "content": "You are a helpful assistant. You can answer with two types of messages: message and picture. "
                           "If user asks you to draw or paint something, you try to figure out what they want to be "
                           "drawn and reply with a description of the picture "
                           "user asked for with the following format: '[picture] description'. "
                           "Do not add 'the picture is a' in the beginning."
                           "For example: '[picture] a cat sitting on a chair'. "
                           "You should not add anything to the description other than what the user asked for."
                           "The description of the picture should be in English, you should translate it if necessary. "
                           "In other cases you reply with a message in the following format: '[message] message'."
            }
        ]
        history = self.cursor.fetchall()
        result.extend(
            {"role": role, "content": message}
            for role, message, _ in sorted(history, key=lambda x: x[2])
        )
        return result

    def get_chats(self, user_id: int) -> list[str]:
        self.cursor.execute(
            "SELECT DISTINCT chat_id "
            "FROM messages "
            "WHERE user_id = ?"
            "ORDER BY timestamp DESC",
            (user_id,)
        )
        return [chat_id for chat_id, in self.cursor.fetchall()]


db = SQLiteRepository(db_path="gpt.db")


async def get_picture(description: str):
    try:
        response = await openai.Image.acreate(
            prompt=f"Painting of a {description.lower()}",
        )
        return response.data[0].url
    except openai.error.OpenAIError as error:
        print(error)
    return None


async def handle_message(update: Update, context):
    chat_id = update.effective_chat.id
    print(f"New message from {chat_id}: {update.message.text}")
    db.add_message(chat_id, "user", update.message.text)
    messages = db.get_messages(chat_id)
    print(f"Messages history for {chat_id}: {messages}")

    gpt_response = await openai.ChatCompletion.acreate(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0,
    )

    message = gpt_response.choices[0].message.content
    print(f"Response from GPT to {chat_id}: {message}")
    db.add_message(chat_id, "assistant", message)

    message_type = message.split(" ")[0]
    match message_type:
        case "[message]":
            await context.bot.send_message(
                chat_id=chat_id,
                text=message[10:],
            )
        case "[picture]":
            picture_url = await get_picture(message[10:])
            if picture_url is None:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Sorry, I can't draw this picture",
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=picture_url,
                )


def main():
    print("Starting bot")
    app = ApplicationBuilder().token(os.environ.get("TOKEN")).build()
    app.add_handler(CommandHandler("start", handle_message))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    openai.api_key = os.environ.get("OPENAI_API_KEY")
    app.run_polling()


if __name__ == "__main__":
    main()
