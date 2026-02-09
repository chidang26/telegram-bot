import os
import random
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("BOT_TOKEN")

# ---------- Helpers ----------
def _get_guess_state(context: ContextTypes.DEFAULT_TYPE):
    # user_data là riêng cho từng user
    return context.user_data.setdefault("guess_game", {"active": False, "target": None, "tries": 0})

# ---------- Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Xin chào! Mình là bot mini game.\n\n"
        "Lệnh nhanh:\n"
        "• /guess_start - bắt đầu game đoán số (1-100)\n"
        "• /guess <so> - đoán số\n"
        "• /guess_stop - dừng game đoán số\n"
        "• /dice - tung xúc xắc đấu bot\n"
        "• /rps rock|paper|scissors - oẳn tù tì\n"
        "• /help - xem lại hướng dẫn"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# --- Guess number game ---
async def guess_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = _get_guess_state(context)
    st["active"] = True
    st["target"] = random.randint(1, 100)
    st["tries"] = 0
    await update.message.reply_text("✅ Bắt đầu game ĐOÁN SỐ! Mình đã chọn 1 số từ 1 đến 100. Dùng /guess <số> để đoán.")

async def guess_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = _get_guess_state(context)
    if not st["active"]:
        return await update.message.reply_text("Game đoán số đang không chạy. Dùng /guess_start để bắt đầu.")
    st["active"] = False
    target = st["target"]
    st["target"] = None
    await update.message.reply_text(f"🛑 Đã dừng game. Số mình chọn là: {target}")

async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = _get_guess_state(context)
    if not st["active"]:
        return await update.message.reply_text("Bạn chưa bắt đầu game. Dùng /guess_start trước nhé.")

    if not context.args:
        return await update.message.reply_text("Cú pháp: /guess <số>  (vd: /guess 42)")

    try:
        g = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Bạn phải nhập số nguyên. Ví dụ: /guess 42")

    if g < 1 or g > 100:
        return await update.message.reply_text("Số phải trong khoảng 1-100.")

    st["tries"] += 1
    target = st["target"]

    if g == target:
        tries = st["tries"]
        st["active"] = False
        st["target"] = None
        await update.message.reply_text(f"🎉 ĐÚNG RỒI! Bạn đoán {tries} lần mới ra. Dùng /guess_start để chơi lại.")
    elif g < target:
        await update.message.reply_text("⬆️ Cao hơn!")
    else:
        await update.message.reply_text("⬇️ Thấp hơn!")

# --- Dice game ---
async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Telegram có emoji dice thật, nhưng để dễ so sánh dùng random cũng được
    user_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)

    if user_roll > bot_roll:
        result = "🏆 Bạn thắng!"
    elif user_roll < bot_roll:
        result = "😅 Bot thắng!"
    else:
        result = "🤝 Hòa!"

    await update.message.reply_text(
        f"🎲 Bạn: {user_roll}\n"
        f"🎲 Bot: {bot_roll}\n"
        f"{result}"
    )

# --- Rock Paper Scissors ---
async def rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Cú pháp: /rps rock|paper|scissors  (vd: /rps rock)")

    user = context.args[0].lower().strip()
    mapping = {"rock": "🪨 rock", "paper": "📄 paper", "scissors": "✂️ scissors"}
    if user not in mapping:
        return await update.message.reply_text("Bạn nhập sai. Dùng: rock / paper / scissors")

    bot = random.choice(list(mapping.keys()))

    # rules
    if user == bot:
        outcome = "🤝 Hòa!"
    elif (user, bot) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}:
        outcome = "🏆 Bạn thắng!"
    else:
        outcome = "😅 Bot thắng!"

    await update.message.reply_text(
        f"Bạn chọn: {mapping[user]}\n"
        f"Bot chọn: {mapping[bot]}\n"
        f"{outcome}"
    )

# --- Optional: chat text shortcut ---
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip().lower()

    # Nếu user đang chơi đoán số mà họ chỉ gõ "42" (không /guess) thì vẫn nhận
    st = _get_guess_state(context)
    if st["active"] and txt.isdigit():
        context.args = [txt]  # “giả lập” args cho /guess
        return await guess(update, context)

    await update.message.reply_text("Gõ /help để xem các trò chơi 🎮")

def main():
    if not TOKEN:
        raise RuntimeError("Thiếu BOT_TOKEN. Hãy set biến môi trường BOT_TOKEN trước khi chạy.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
