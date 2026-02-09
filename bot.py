import random
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

import os
import re
import time
import asyncio
import logging
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

import aiosqlite
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest, Forbidden

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)



TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# ====== CONFIG ======
# Admin Telegram user IDs (dùng /myid để lấy)
ADMIN_USER_IDS = {7997416485}  # <-- sửa: thay bằng user_id của bạn, có thể thêm nhiều id

# Broadcast rate limit (an toàn)
BROADCAST_SLEEP_SECONDS = 0.05  # 20 msg/giây (thực tế tuỳ tài khoản/bot, để thấp cho an toàn)

# Anti-spam
MAX_MSG_PER_WINDOW = 6          # tối đa 6 tin
WINDOW_SECONDS = 10             # trong 10 giây
MUTE_SECONDS = 10 * 60          # mute 10 phút khi flood (nếu bot có quyền)

# Filter link (xoá link từ người không phải admin)
BLOCK_LINKS = True
LINK_RE = re.compile(r"(https?://|t\.me/|www\.)", re.IGNORECASE)

# Banned keywords (tuỳ chỉnh)
BANNED_KEYWORDS = [

]
# ====================

# flood tracker: (chat_id, user_id) -> deque[timestamps]
_flood: Dict[Tuple[int, int], Deque[float]] = defaultdict(deque)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            created_at INTEGER NOT NULL
        )
        """)
        await db.commit()

def is_admin_user(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


async def add_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO subscribers(user_id, created_at) VALUES(?, ?)",
            (user_id, int(time.time()))
        )
        await db.commit()


async def remove_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
        await db.commit()


async def list_subscribers() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM subscribers")
        rows = await cur.fetchall()
    return [r[0] for r in rows]

# GAMEEEEE

# ---------- Helpers ----------
def _get_guess_state(context: ContextTypes.DEFAULT_TYPE):
    # user_data là riêng cho từng user
    return context.user_data.setdefault("guess_game", {"active": False, "target": None, "tries": 0})

# ---------- Commands ----------
async def game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Xin chào! Mình là bot mini game.\n\n"
        "Lệnh nhanh:\n"
        "• /guess_start - bắt đầu game đoán số (1-100)\n"
        "• /guess <so> - đoán số\n"
        "• /guess_stop - dừng game đoán số\n"
        "• /dice - tung xúc xắc đấu bot\n"
        "• /rps rock|paper|scissors - oẳn tù tì\n"
        "• /game_help - xem lại hướng dẫn"
    )

async def game_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await game_start(update, context)

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

# GAMEEEEE

# ===== Commands =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_subscriber(update.effective_user.id)
    await update.message.reply_text(
        "✅ Bạn đã /start.\n"
        "• /subscribe: bật nhận thông báo\n"
        "• /unsubscribe: tắt nhận thông báo\n"
        "• /help: xem lệnh\n"
        "• /myid: xem user id\n"
        "• /game_start: bắt đầu game vui:))\n"
    )


# Menu command
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Lệnh người dùng:\n"
        "• /start\n"
        "• /subscribe\n"
        "• /unsubscribe\n"
        "• /myid\n\n"
        "• /game_start: bắt đầu game vui:))\n"
        "Lệnh admin:\n"
        "• /broadcast <nội dung>\n"
        "• /stats\n"
        "• /sendnow\n"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your user_id: {update.effective_user.id}")


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_subscriber(update.effective_user.id)
    await update.message.reply_text("✅ Đã bật nhận thông báo.")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await remove_subscriber(update.effective_user.id)
    await update.message.reply_text("🛑 Đã tắt nhận thông báo.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        return await update.message.reply_text("⛔ Bạn không có quyền.")
    subs = await list_subscribers()
    await update.message.reply_text(f"👥 Subscribers: {len(subs)}")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        return await update.message.reply_text("⛔ Bạn không có quyền.")

    text = " ".join(context.args).strip()
    if not text:
        return await update.message.reply_text("Cú pháp: /broadcast <nội dung>")

    subs = await list_subscribers()
    if not subs:
        return await update.message.reply_text("Chưa có subscriber nào.")

    ok = 0
    fail = 0

    await update.message.reply_text(f"📣 Bắt đầu gửi cho {len(subs)} người...")

    for uid in subs:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            ok += 1
        except (Forbidden, BadRequest):
            # user chặn bot hoặc chat không tồn tại => xoá khỏi danh sách
            await remove_subscriber(uid)
            fail += 1
        except Exception:
            fail += 1

        await asyncio.sleep(BROADCAST_SLEEP_SECONDS)

    await update.message.reply_text(f"✅ Xong. OK: {ok}, Fail: {fail} (fail sẽ tự loại khỏi list nếu chặn bot).")


# ===== Anti-spam handlers =====
async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.from_user:
        return

    chat = update.effective_chat
    user = msg.from_user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Bỏ qua admin bot owner (và có thể bỏ qua admin group)
    if is_admin_user(user.id):
        return

    text = (msg.text or msg.caption or "").lower()

    # 1) Link filter
    if BLOCK_LINKS and text and LINK_RE.search(text):
        try:
            await msg.delete()
            return
        except Exception:
            pass

    # 2) Banned keywords
    for kw in BANNED_KEYWORDS:
        if kw.lower() in text:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # 3) Flood control
    key = (chat.id, user.id)
    now = time.time()
    dq = _flood[key]
    dq.append(now)
    while dq and now - dq[0] > WINDOW_SECONDS:
        dq.popleft()

    if len(dq) >= MAX_MSG_PER_WINDOW:
        # cố gắng mute nếu bot có quyền
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions={},  # no permissions => muted
                until_date=int(now + MUTE_SECONDS),
            )
            await msg.reply_text(f"🚫 @{user.username or user.first_name} spam quá nhanh, bị mute {MUTE_SECONDS//60} phút.")
        except Exception:
            # nếu không mute được thì chỉ cảnh báo
            try:
                await msg.reply_text("🚫 Bạn nhắn quá nhanh, vui lòng chậm lại.")
            except Exception:
                pass
        finally:
            dq.clear()


async def sendnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_user(update.effective_user.id):
        return await update.message.reply_text("⛔ Bạn không có quyền.")

    if not update.message.reply_to_message:
        return await update.message.reply_text("Cú pháp: Reply vào tin cần gửi rồi gõ /sendnow")

    subs = await list_subscribers()
    if not subs:
        return await update.message.reply_text("Chưa có subscriber nào.")

    ok = 0
    fail = 0
    src = update.message.reply_to_message

    await update.message.reply_text(f"📣 Đang gửi tới {len(subs)} người...")

    for uid in subs:
        try:
            # copy y nguyên nội dung (text/ảnh/video/file)
            await src.copy(chat_id=uid)
            ok += 1
        except (Forbidden, BadRequest):
            await remove_subscriber(uid)  # ai chặn bot thì tự loại khỏi list
            fail += 1
        except Exception:
            fail += 1

        await asyncio.sleep(BROADCAST_SLEEP_SECONDS)

    await update.message.reply_text(f"✅ Xong. OK: {ok}, Fail: {fail}")
 
def main():
    if not TOKEN:
        raise RuntimeError("Thiếu BOT_TOKEN. Hãy set biến môi trường BOT_TOKEN trước khi chạy.")

    app = Application.builder().token(TOKEN).build()

    # async def post_init(application):
    #     await init_db()
    # app.post_init = post_init

    # lệnh cho người dùng
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))

    # lệnh admin
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("sendnow", sendnow))

    app.add_handler(MessageHandler(filters.ALL, anti_spam), group=1)
# GAMEEEE
    # ===== COMMAND HANDLERS =====
    app.add_handler(CommandHandler("game_start", game_start))
    app.add_handler(CommandHandler("game_help", game_help))

    app.add_handler(CommandHandler("guess_start", guess_start))
    app.add_handler(CommandHandler("guess", guess))
    app.add_handler(CommandHandler("guess_stop", guess_stop))

    app.add_handler(CommandHandler("dice", dice))
    app.add_handler(CommandHandler("rps", rps))

    # ===== TEXT HANDLER (shortcut đoán số) =====
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
# GAMEEEE

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
