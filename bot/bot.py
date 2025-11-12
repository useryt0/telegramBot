import os
import aiohttp
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BotCommand,
    CallbackQuery,  
    Message,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import asyncio

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not TELEGRAM_TOKEN or not API_BASE_URL:
    raise ValueError("Missing TELEGRAM_TOKEN or API_BASE_URL in .env")

# ALLOWED_USER_IDS = [int(uid) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip()]
ALLOWED_USER_IDS = [
    # add more IDs below as needed
    # 5314,
]
ITEMS_PER_PAGE = 8


# ========== Decorator ==========
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = None
        if getattr(update, "effective_user", None):
            user_id = update.effective_user.id
        elif getattr(update, "callback_query", None):
            user_id = update.callback_query.from_user.id
        if user_id not in ALLOWED_USER_IDS:
            if getattr(update, "message", None):
                await update.message.reply_text("🚫 You are not authorized to use this bot.")
            elif getattr(update, "callback_query", None):
                await update.callback_query.answer("🚫 You are not authorized", show_alert=True)
            return
        return await func(update, context)
    return wrapper


# ========== API Helpers ==========
async def fetch_pending(endpoint):
    headers = {"X-BOT-TOKEN": str(BOT_TOKEN)}
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return await resp.json()
                print(f"⚠️ Failed fetch {endpoint}: {resp.status} -> {text}")
    except Exception as e:
        print("⚠️ Exception fetch_pending:", e)
    return []


async def update_status(endpoint, data):
    headers = {"X-BOT-TOKEN": str(BOT_TOKEN), "Content-Type": "application/json"}
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as resp:
                text = await resp.text()
                print(f"📡 update_status {endpoint}: {resp.status} -> {text}")
                return resp.status
    except Exception as e:
        print("⚠️ Exception update_status:", e)
        return None


# ========== Paging Helpers ==========
def paginate(items, page, per_page=ITEMS_PER_PAGE):
    start, end = page * per_page, (page + 1) * per_page
    return items[start:end], len(items) > end


# ========== Telegram UI Builders ==========
def build_list_page(items, page, has_next):
    keyboard = []
    for item in items:
        if item["type"] == "org":
            label = f"🏢 {item.get('org_name','-')} ({item.get('city','-')})"
        else:
            label = f"👤 {item.get('first_name','-')} {item.get('last_name','-')} ({item.get('city','-')})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"view_{item['type']}_{item['id']}_{page}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"open_pending_{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"open_pending_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_list")])
    return InlineKeyboardMarkup(keyboard)


def build_detail_view(item, page, is_from_list=True):
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{item['type']}_{item['id']}_{page}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{item['type']}_{item['id']}_{page}"),
        ],
        [
            InlineKeyboardButton("📧 Verify Email", callback_data=f"verify_{item['type']}_{item['id']}_{page}"),
            InlineKeyboardButton("✏️ Set Max Children", callback_data=f"setmax_{item['type']}_{item['id']}_{page}"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"open_pending_{page}")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Callback Handling ==========
@admin_only
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    data = cq.data

    # --- Paging & Back: edit in place ---
    if data.startswith("open_pending_"):
        page = int(data.split("_")[-1])
        await _render_list_in_place(cq, context, page)
        return

    # --- View detail ---
    if data.startswith("view_"):
        _, entity, item_id_s, page_s = data.split("_")
        item_id, page = int(item_id_s), int(page_s)
        endpoint = "bot/orgs/pending/" if entity == "org" else "bot/specs/pending/"
        items = await fetch_pending(endpoint)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            await cq.edit_message_text("⚠️ Item not found.")
            return
        item["type"] = entity
        if entity == "org":
            text = (
                f"🏢 <b>Organisation #{item['id']}</b>\n"
                f"<b>Name:</b> {item.get('org_name','-')}\n"
                f"<b>Email:</b> {item.get('email','-')} ({'confirmed' if item.get('is_email_confirmed') else 'unconfirmed'})\n"
                f"<b>Address:</b> {item.get('address','-')}\n"
                f"<b>City:</b> {item.get('city','-')}\n"
                f"<b>Status:</b> {item.get('status','-')}"
            )
        else:
            text = (
                f"👤 <b>Specialist #{item['id']}</b>\n"
                f"<b>Name:</b> {item.get('first_name','-')} {item.get('last_name','-')}\n"
                f"<b>Email:</b> {item.get('email','-')} ({'confirmed' if item.get('is_email_confirmed') else 'unconfirmed'})\n"
                f"<b>City:</b> {item.get('city','-')}\n"
                f"<b>Status:</b> {item.get('status','-')}"
            )

        context.user_data['list_msg'] = (cq.message.chat_id, cq.message.message_id)
        
        await cq.edit_message_text(text=text, parse_mode="HTML",
                                   reply_markup=build_detail_view(item, page))
        return

    # --- Close ---
    if data == "close_list":
        try:
            await cq.message.delete()
        except Exception:
            pass
        return

    # --- Approve / Reject / Verify / Setmax ---
    if any(data.startswith(prefix) for prefix in ["approve_", "reject_", "verify_", "setmax_"]):
        action, entity, item_id_s, page_s = data.split("_")
        item_id, page = int(item_id_s), int(page_s)
        endpoint = f"bot/orgs/{item_id}/update/" if entity == "org" else f"bot/specs/{item_id}/update/"
        payload = {}
        if action == "approve":
            payload["status"] = "verified"
        elif action == "reject":
            payload["status"] = "rejected"
        elif action == "verify":
            payload["is_email_confirmed"] = True
        elif action == "setmax":
            await cq.edit_message_text("✏️ Send the new max children count:")
            context.user_data["awaiting_max"] = (entity, item_id, page)
            return

        status_code = await update_status(endpoint, payload)
        if status_code == 200:
            await _render_list_in_place(cq, context, page)
        else:
            await cq.edit_message_text(f"⚠️ Failed to update {entity} #{item_id}. (HTTP {status_code})")


# ========== Persistent Main Keyboard ==========
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🔍 Check Pending"), KeyboardButton("❌ Close Keyboard")]],
    resize_keyboard=True,
    one_time_keyboard=False
)


# ========== Commands ==========
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Use the keyboard or the bot menu (≡) to run actions.",
        reply_markup=MAIN_KEYBOARD
    )

# --- helper: get combined pending ---
async def _get_combined_pending():
    orgs = await fetch_pending("bot/orgs/pending/")
    specs = await fetch_pending("bot/specs/pending/")
    return [{"type": "org", **o} for o in orgs] + [{"type": "spec", **s} for s in specs]

# --- helper: render list in-place for a CallbackQuery (always edit, never send) ---
async def _render_list_in_place(cq: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, page: int):
    combined = await _get_combined_pending()
    if not combined:
        try:
            await cq.edit_message_text("✅ No pending organisations or specialists.")
        except Exception:
            pass
        context.user_data['list_msg'] = (cq.message.chat_id, cq.message.message_id)
        return

    items, has_next = paginate(combined, page)
    markup = build_list_page(items, page, has_next)
    text = f"📋 Pending Registrations (Page {page+1})"
    try:
        await cq.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            print(f"⚠️ _render_list_in_place edit failed: {e}")
    context.user_data['list_msg'] = (cq.message.chat_id, cq.message.message_id)

@admin_only
async def check_pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_pending_page(update, context, page=0)
    
async def show_pending_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    combined = await _get_combined_pending()

    if isinstance(update_or_query, Update) and update_or_query.callback_query:
        cq = update_or_query.callback_query
        await _render_list_in_place(cq, context, page)
        return
    if isinstance(update_or_query, CallbackQuery):
        await _render_list_in_place(update_or_query, context, page)
        return

    if not combined:
        if isinstance(update_or_query, Update) and update_or_query.message:
            await update_or_query.message.reply_text("✅ No pending organisations or specialists.", reply_markup=MAIN_KEYBOARD)
        return

    items, has_next = paginate(combined, page)
    markup = build_list_page(items, page, has_next)
    text = f"📋 Pending Registrations (Page {page+1})"
    
    if isinstance(update_or_query, Update) and update_or_query.message:
        sent = await update_or_query.message.reply_html(text, reply_markup=markup)
        context.user_data['list_msg'] = (sent.chat_id, sent.message_id)


# ========== Text Input ==========
@admin_only
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔍 Check Pending", "📋 Check Pending", "/check_pending"]:
        await show_pending_page(update, context, page=0)
    elif text == "❌ Close Keyboard":
        await update.message.reply_text("Keyboard closed.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Use the menu below.", reply_markup=MAIN_KEYBOARD)



@admin_only
async def handle_followup_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_max" not in context.user_data:
        return
    entity, item_id, page = context.user_data.pop("awaiting_max")
    try:
        max_children = int(update.message.text)
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid integer.")
        return
    endpoint = f"bot/orgs/{item_id}/update/" if entity == "org" else f"bot/specs/{item_id}/update/"
    payload = {"max_children_allowed": max_children}
    status_code = await update_status(endpoint, payload)
    if status_code != 200:
        await update.message.reply_text(f"⚠️ Failed to update {entity} #{item_id}.")
        return

    await update.message.reply_text(f"✏️ Max children updated to {max_children} for {entity} #{item_id}.")

    # --- edit the original list message, do not create a new one ---
    if 'list_msg' in context.user_data:
        chat_id, msg_id = context.user_data['list_msg']
        class FakeCQ:
            def __init__(self, chat_id, msg_id):
                self.message = type("Msg", (), {"chat_id": chat_id, "message_id": msg_id})()
        fake_cq = FakeCQ(chat_id, msg_id)
        await show_pending_page(fake_cq, context, page)


# ========== Entrypoint & set commands ==========
async def set_bot_commands(application):
    try:
        await application.bot.set_my_commands([BotCommand("check_pending", "Check pending approvals")])
    except Exception as e:
        print("⚠️ set_my_commands failed:", e)


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(set_bot_commands).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check_pending", check_pending_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_followup_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()