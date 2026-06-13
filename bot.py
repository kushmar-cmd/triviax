"""
🎯 בוט טריוויה ישראלי — גרסה 2
8 קטגוריות | סולו + קבוצתי | Claude AI
"""

import os
import json
import asyncio
import logging
from anthropic import AsyncAnthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN        = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
anthropic        = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# ══════════════════════════════════════════════════════════
#  קטגוריות
# ══════════════════════════════════════════════════════════

CATEGORIES = {
    "sport":    ("⚽", "ספורט וכדורגל"),
    "history":  ("🇮🇱", "היסטוריה ישראלית"),
    "music":    ("🎵", "מוזיקה עולמית"),
    "ilmusic":  ("🎶", "מוזיקה ישראלית"),
    "general":  ("🧠", "ידע כללי"),
    "geo":      ("🌍", "גיאוגרפיה"),
    "cinema":   ("🎬", "קולנוע וטלוויזיה"),
    "science":  ("🔬", "מדע וטבע"),
}

DIFFICULTIES = {
    "easy":   "🟢 קל",
    "medium": "🟡 בינוני",
    "hard":   "🔴 קשה",
}

# זמן מענה בשניות במצב קבוצתי
GROUP_TIMEOUT = 20

# ══════════════════════════════════════════════════════════
#  עזרים
# ══════════════════════════════════════════════════════════

def score_emoji(score: int) -> str:
    if score >= 15: return "🏆"
    if score >= 10: return "🥇"
    if score >= 5:  return "🥈"
    return "🎯"


def cat_label(key: str) -> str:
    e, n = CATEGORIES[key]
    return f"{e} {n}"


def build_category_keyboard() -> InlineKeyboardMarkup:
    keys = list(CATEGORIES.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i+2]:
            e, n = CATEGORIES[k]
            row.append(InlineKeyboardButton(f"{e} {n}", callback_data=f"cat:{k}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def build_difficulty_keyboard(cat: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"diff:{cat}:{key}")]
        for key, label in DIFFICULTIES.items()
    ]
    return InlineKeyboardMarkup(rows)


def build_answer_keyboard(options: list, cat: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{i+1}. {opt}", callback_data=f"ans:{cat}:{i}")]
        for i, opt in enumerate(options)
    ]
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════════════
#  יצירת שאלה עם Claude
# ══════════════════════════════════════════════════════════

CATEGORY_PROMPTS = {
    "sport":   "ספורט וכדורגל (ישראלי ועולמי)",
    "history": "היסטוריה ישראלית",
    "music":   "מוזיקה עולמית (להקות, אמנים, אלבומים)",
    "ilmusic": "מוזיקה ישראלית (זמרים, להקות, שירים)",
    "general": "ידע כללי מגוון",
    "geo":     "גיאוגרפיה עולמית ועיר בירה",
    "cinema":  "קולנוע וטלוויזיה (ישראלי ועולמי)",
    "science": "מדע וטבע (ביולוגיה, פיזיקה, כימיה, חלל)",
}

async def generate_question(cat: str, difficulty: str) -> dict:
    diff_map = {"easy": "קלה", "medium": "בינונית", "hard": "קשה"}
    topic = CATEGORY_PROMPTS.get(cat, "ידע כללי")
    diff_he = diff_map.get(difficulty, "בינונית")

    prompt = (
        f"צור שאלת טריוויה על הנושא: {topic}. רמת קושי: {diff_he}.\n"
        "השאלה חייבת להיות בעברית.\n"
        "החזר JSON בלבד — ללא backticks, ללא טקסט לפני/אחרי.\n"
        "מבנה מדויק:\n"
        '{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"..."}\n'
        "correct = אינדקס (0-3) של התשובה הנכונה."
    )

    resp = await anthropic.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ══════════════════════════════════════════════════════════
#  ניהול ניקוד
# ══════════════════════════════════════════════════════════

def get_user_score(bot_data: dict, uid: str) -> dict:
    scores = bot_data.setdefault("scores", {})
    return scores.setdefault(uid, {"score": 0, "total": 0, "name": "שחקן"})


def update_score(bot_data: dict, uid: str, name: str, correct: bool):
    d = get_user_score(bot_data, uid)
    d["name"]  = name
    d["total"] += 1
    if correct:
        d["score"] += 1

# ══════════════════════════════════════════════════════════
#  ניהול משחקי קבוצה
# ══════════════════════════════════════════════════════════

def get_group_game(bot_data: dict, chat_id: int) -> dict | None:
    return bot_data.get("group_games", {}).get(chat_id)


def set_group_game(bot_data: dict, chat_id: int, game: dict | None):
    bot_data.setdefault("group_games", {})
    if game is None:
        bot_data["group_games"].pop(chat_id, None)
    else:
        bot_data["group_games"][chat_id] = game

# ══════════════════════════════════════════════════════════
#  פקודות
# ══════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "חבר"
    is_group = update.effective_chat.type in ("group", "supergroup")

    if is_group:
        text = (
            f"👋 שלום {name}! אני בוט הטריוויה הישראלי.\n\n"
            "📋 פקודות:\n"
            "/trivia — שאלה קבוצתית (כולם יכולים לענות!)\n"
            "/score — הניקוד שלך\n"
            "/top — טבלת מובילים\n"
            "/help — עזרה"
        )
    else:
        text = (
            f"🎯 ברוך הבא {name}!\n\n"
            "📋 פקודות:\n"
            "/play — משחק סולו\n"
            "/trivia — שאלה קבוצתית\n"
            "/score — הניקוד שלך\n"
            "/top — טבלת מובילים\n"
            "/help — עזרה"
        )
    await update.message.reply_text(text)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*🎯 בוט טריוויה ישראלי*\n\n"
        "8 קטגוריות:\n"
        "⚽ ספורט וכדורגל\n"
        "🇮🇱 היסטוריה ישראלית\n"
        "🎵 מוזיקה עולמית\n"
        "🎶 מוזיקה ישראלית\n"
        "🧠 ידע כללי\n"
        "🌍 גיאוגרפיה\n"
        "🎬 קולנוע וטלוויזיה\n"
        "🔬 מדע וטבע\n\n"
        "*מצבי משחק:*\n"
        "🎮 /play — סולו (אתה מול המחשב)\n"
        "👥 /trivia — קבוצתי (מי שעונה ראשון מנצח)\n\n"
        "⚡ _שאלות נוצרות בזמן אמת ע\"י Claude AI_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_play(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """סולו — בחירת קטגוריה"""
    await update.message.reply_text(
        "🎮 *משחק סולו — בחר קטגוריה:*",
        parse_mode="Markdown",
        reply_markup=build_category_keyboard(),
    )


async def cmd_trivia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """קבוצתי — בחירת קטגוריה"""
    chat_id = update.effective_chat.id
    existing = get_group_game(ctx.bot_data, chat_id)
    if existing:
        await update.message.reply_text("⏳ כבר יש שאלה פעילה! ענו עליה קודם.")
        return

    await update.message.reply_text(
        "👥 *משחק קבוצתי — בחר קטגוריה:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{e} {n}", callback_data=f"gcat:{k}")]
            for k, (e, n) in list(CATEGORIES.items())[:4]
        ] + [
            [InlineKeyboardButton(f"{e} {n}", callback_data=f"gcat:{k}")]
            for k, (e, n) in list(CATEGORIES.items())[4:]
        ]),
    )


async def cmd_score(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.effective_user.id)
    d    = get_user_score(ctx.bot_data, uid)
    s, t = d["score"], d["total"]
    pct  = int(s / t * 100) if t else 0
    await update.message.reply_text(
        f"{score_emoji(s)} *הניקוד שלך:*\n\n"
        f"✅ נכון: {s}/{t}\n"
        f"📊 הצלחה: {pct}%",
        parse_mode="Markdown",
    )


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    scores = ctx.bot_data.get("scores", {})
    if not scores:
        await update.message.reply_text("אין ניקודים עדיין — /play כדי להיות ראשון! 🏆")
        return

    top = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines = ["🏆 *טבלת מובילים:*\n"]
    for i, (uid, d) in enumerate(top):
        lines.append(f"{medals[i]} {d.get('name','???')}: {d['score']} נקודות ({d['total']} שאלות)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ══════════════════════════════════════════════════════════
#  Callback router
# ══════════════════════════════════════════════════════════

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── סולו: בחירת קטגוריה ────────────────────────────
    if data.startswith("cat:"):
        cat = data.split(":")[1]
        ctx.user_data["solo_cat"] = cat
        await query.edit_message_text(
            f"🎮 *{cat_label(cat)}*\nבחר רמת קושי:",
            parse_mode="Markdown",
            reply_markup=build_difficulty_keyboard(cat),
        )

    # ── סולו: בחירת קושי → שאלה ────────────────────────
    elif data.startswith("diff:"):
        _, cat, difficulty = data.split(":")
        await query.edit_message_text(f"⏳ יוצר שאלה ב{cat_label(cat)}...")
        try:
            q = await generate_question(cat, difficulty)
        except Exception as e:
            logger.error(f"generate_question error: {e}")
            await query.edit_message_text("❌ שגיאה. נסה שוב עם /play")
            return

        ctx.user_data["solo_q"]    = q
        ctx.user_data["solo_cat"]  = cat
        ctx.user_data["solo_diff"] = difficulty

        await query.edit_message_text(
            f"🎮 *{cat_label(cat)} | {DIFFICULTIES[difficulty]}*\n\n{q['question']}",
            parse_mode="Markdown",
            reply_markup=build_answer_keyboard(q["options"], cat),
        )

    # ── סולו: תשובה ────────────────────────────────────
    elif data.startswith("ans:"):
        _, cat, chosen_str = data.split(":")
        chosen = int(chosen_str)
        q      = ctx.user_data.get("solo_q")
        diff   = ctx.user_data.get("solo_diff", "medium")

        if not q:
            await query.edit_message_text("משחק פג. /play למשחק חדש.")
            return

        correct      = q["correct"]
        correct_text = q["options"][correct]
        uid  = str(query.from_user.id)
        name = query.from_user.first_name or "שחקן"
        is_correct = (chosen == correct)

        update_score(ctx.bot_data, uid, name, is_correct)
        d = get_user_score(ctx.bot_data, uid)
        ctx.user_data.pop("solo_q", None)

        result = "✅ *נכון!*" if is_correct else "❌ *לא נכון*"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 שאלה נוספת באותה קטגוריה", callback_data=f"diff:{cat}:{diff}")],
            [InlineKeyboardButton("🗂 קטגוריה אחרת", callback_data="back_to_cats")],
        ])

        await query.edit_message_text(
            f"{result}\n\n"
            f"🎵 תשובה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"📊 ניקוד: {d['score']}/{d['total']}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    # ── חזרה לקטגוריות ──────────────────────────────────
    elif data == "back_to_cats":
        await query.edit_message_text(
            "🎮 *בחר קטגוריה:*",
            parse_mode="Markdown",
            reply_markup=build_category_keyboard(),
        )

    # ── קבוצתי: בחירת קטגוריה ──────────────────────────
    elif data.startswith("gcat:"):
        cat = data.split(":")[1]
        ctx.chat_data["group_cat"] = cat
        await query.edit_message_text(
            f"👥 *{cat_label(cat)}*\nבחר רמת קושי:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(label, callback_data=f"gdiff:{cat}:{key}")]
                for key, label in DIFFICULTIES.items()
            ]),
        )

    # ── קבוצתי: בחירת קושי → שאלה ─────────────────────
    elif data.startswith("gdiff:"):
        _, cat, difficulty = data.split(":")
        chat_id = update.effective_chat.id

        if get_group_game(ctx.bot_data, chat_id):
            return  # כבר יש משחק

        await query.edit_message_text(f"⏳ יוצר שאלה קבוצתית ב{cat_label(cat)}...")

        try:
            q = await generate_question(cat, difficulty)
        except Exception as e:
            logger.error(f"group generate_question error: {e}")
            await query.edit_message_text("❌ שגיאה. נסה שוב עם /trivia")
            return

        # שמור משחק קבוצתי
        game = {
            "q":          q,
            "cat":        cat,
            "difficulty": difficulty,
            "answered":   False,
        }
        set_group_game(ctx.bot_data, chat_id, game)

        keyboard = build_answer_keyboard(q["options"], cat)
        msg = await query.edit_message_text(
            f"👥 *{cat_label(cat)} | {DIFFICULTIES[difficulty]}*\n"
            f"⏱ {GROUP_TIMEOUT} שניות לענות!\n\n"
            f"{q['question']}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        # טיימר — אם לא ענו, חשוף תשובה
        async def timeout_reveal():
            await asyncio.sleep(GROUP_TIMEOUT)
            current = get_group_game(ctx.bot_data, chat_id)
            if current and not current.get("answered"):
                set_group_game(ctx.bot_data, chat_id, None)
                correct_text = q["options"][q["correct"]]
                try:
                    await ctx.bot.send_message(
                        chat_id,
                        f"⏰ *הזמן עבר!* אף אחד לא ענה נכון.\n\n"
                        f"✅ התשובה: *{correct_text}*\n"
                        f"💡 {q.get('explanation','')}\n\n"
                        f"כתבו /trivia לשאלה הבאה!",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        asyncio.create_task(timeout_reveal())

    # ── קבוצתי: תשובה ───────────────────────────────────
    elif data.startswith("gans:"):
        # מטפל בתשובות קבוצתיות — כפתורים אלו נוצרים ע"י build_answer_keyboard עם prefix "ans:"
        # (ראה למטה — גם "ans:" מנותב לכאן אם יש משחק קבוצתי פעיל)
        pass

# ══════════════════════════════════════════════════════════
#  תשובות קבוצתיות — כפתורי "ans:" בהקשר קבוצה
# ══════════════════════════════════════════════════════════

async def on_group_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    אם ה-callback "ans:..." מגיע מקבוצה שיש בה משחק פעיל —
    מטפל פה במקום ב-on_callback.
    """
    query   = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = update.effective_chat.id

    game = get_group_game(ctx.bot_data, chat_id)
    if not game or game.get("answered"):
        return  # אין משחק פעיל / כבר נענה

    _, cat, chosen_str = data.split(":")
    chosen    = int(chosen_str)
    q         = game["q"]
    correct   = q["correct"]
    is_correct = (chosen == correct)

    # סמן כנענה (גם אם שגוי — מונע כפילויות)
    game["answered"] = True
    set_group_game(ctx.bot_data, chat_id, None)

    uid  = str(query.from_user.id)
    name = query.from_user.first_name or "שחקן"
    correct_text = q["options"][correct]

    update_score(ctx.bot_data, uid, name, is_correct)
    d = get_user_score(ctx.bot_data, uid)

    if is_correct:
        result_text = (
            f"🏆 *{name} ענה נכון ראשון!*\n\n"
            f"✅ תשובה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"📊 ניקוד של {name}: {d['score']}/{d['total']}\n\n"
            f"כתבו /trivia לשאלה הבאה!"
        )
    else:
        result_text = (
            f"❌ *{name} ענה לא נכון.*\n\n"
            f"✅ התשובה הנכונה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"כתבו /trivia לשאלה הבאה!"
        )

    await query.edit_message_text(result_text, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════
#  Router — מחליט אם callback הוא סולו או קבוצתי
# ══════════════════════════════════════════════════════════

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    chat_id = update.effective_chat.id

    # אם יש משחק קבוצתי פעיל ומגיע תשובה → קבוצתי
    if data.startswith("ans:") and get_group_game(ctx.bot_data, chat_id):
        await on_group_answer(update, ctx)
    else:
        await on_callback(update, ctx)

# ══════════════════════════════════════════════════════════
#  הפעלה
# ══════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("play",   cmd_play))
    app.add_handler(CommandHandler("trivia", cmd_trivia))
    app.add_handler(CommandHandler("score",  cmd_score))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("🎯 בוט טריוויה v2 מתחיל...")
    app.run_polling()


if __name__ == "__main__":
    main()
