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


# ===== Commands =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_subscriber(update.effective_user.id)
    await update.message.reply_text(
        "✅ Bạn đã /start.\n"
        "• /subscribe: bật nhận thông báo\n"
        "• /unsubscribe: tắt nhận thông báo\n"
        "• /help: xem lệnh\n"
        "• /myid: xem user id\n"
    )


# Menu command
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Lệnh người dùng:\n"
        "• /start\n"
        "• /subscribe\n"
        "• /unsubscribe\n"
        "• /myid\n\n"
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

    # init db before polling
    app.post_init = lambda application: init_db()


    # lệnh cho người dùng 
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))

    # lệnh của admin 
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("sendnow", sendnow))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # game
    # app.add_handler(CommandHandler("guess_start", guess_start))
    # app.add_handler(CommandHandler("guess_stop", guess_stop))
    # app.add_handler(CommandHandler("guess", guess))

    # app.add_handler(CommandHandler("dice", dice))
    # app.add_handler(CommandHandler("rps", rps))

    # anti-spam for groups
    app.add_handler(MessageHandler(filters.ALL, anti_spam), group=1)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
