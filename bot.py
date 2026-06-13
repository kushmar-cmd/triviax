"""
🎯 בוט טריוויה ישראלי — גרסה 3
10 קטגוריות | סולו + קבוצתי | Claude AI
"""

import os
import json
import random
import asyncio
import logging
from anthropic import AsyncAnthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN         = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
anthropic         = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

GROUP_TIMEOUT = 20

# ══════════════════════════════════════════════════════════
#  קטגוריות
# ══════════════════════════════════════════════════════════

CATEGORIES = {
    "sport":    ("⚽", "ספורט וכדורגל"),
    "history":  ("🇮🇱", "היסטוריה ישראלית"),
    "world":    ("🌐", "היסטוריה עולמית"),
    "music":    ("🎵", "מוזיקה עולמית"),
    "ilmusic":  ("🎶", "מוזיקה ישראלית"),
    "general":  ("🧠", "ידע כללי"),
    "geo":      ("🌍", "גיאוגרפיה"),
    "cinema":   ("🎬", "קולנוע וטלוויזיה"),
    "science":  ("🔬", "מדע וטבע"),
    "mixed":    ("🎲", "מעורב — הכל"),
}

CATEGORY_PROMPTS = {
    "sport":   "ספורט וכדורגל (ישראלי ועולמי)",
    "history": "היסטוריה ישראלית",
    "world":   "היסטוריה עולמית (מלחמות, מנהיגים, אירועים)",
    "music":   "מוזיקה עולמית (להקות, אמנים, אלבומים)",
    "ilmusic": "מוזיקה ישראלית (זמרים, להקות, שירים)",
    "general": "ידע כללי מגוון",
    "geo":     "גיאוגרפיה עולמית ועיר בירה",
    "cinema":  "קולנוע וטלוויזיה (ישראלי ועולמי)",
    "science": "מדע וטבע (ביולוגיה, פיזיקה, כימיה, חלל)",
}

DIFFICULTIES = {
    "easy":   "🟢 קל",
    "medium": "🟡 בינוני",
    "hard":   "🔴 קשה",
}

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


def resolve_cat(cat: str) -> str:
    """אם מעורב — בחר קטגוריה אקראית"""
    if cat == "mixed":
        real_cats = [k for k in CATEGORIES if k != "mixed"]
        return random.choice(real_cats)
    return cat


def build_main_menu(name: str, is_group: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    if is_group:
        text = f"🎯 שלום {name}! בוט טריוויה ישראלי"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 שאלה קבוצתית", callback_data="menu:trivia")],
            [InlineKeyboardButton("📊 הניקוד שלי", callback_data="menu:score"),
             InlineKeyboardButton("🏆 טבלה", callback_data="menu:top")],
        ])
    else:
        text = f"🎯 ברוך הבא {name}!"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 משחק סולו", callback_data="menu:play")],
            [InlineKeyboardButton("👥 שאלה קבוצתית", callback_data="menu:trivia")],
            [InlineKeyboardButton("📊 הניקוד שלי", callback_data="menu:score"),
             InlineKeyboardButton("🏆 טבלה", callback_data="menu:top")],
        ])
    return text, keyboard


def build_category_keyboard(prefix: str = "cat") -> InlineKeyboardMarkup:
    keys = list(CATEGORIES.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i+2]:
            e, n = CATEGORIES[k]
            row.append(InlineKeyboardButton(f"{e} {n}", callback_data=f"{prefix}:{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 תפריט ראשי", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def build_difficulty_keyboard(cat: str, prefix: str = "diff") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}:{cat}:{key}")]
        for key, label in DIFFICULTIES.items()
    ]
    rows.append([InlineKeyboardButton("↩️ חזרה", callback_data=f"back_cats:{prefix}")])
    return InlineKeyboardMarkup(rows)


def build_answer_keyboard(options: list, cat: str, diff: str, prefix: str = "ans") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{i+1}. {opt}", callback_data=f"{prefix}:{cat}:{diff}:{i}")]
        for i, opt in enumerate(options)
    ]
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════════════════
#  יצירת שאלה עם Claude
# ══════════════════════════════════════════════════════════

async def generate_question(cat: str, difficulty: str, asked: list = None) -> dict:
    """
    cat: קטגוריה אמיתית (לא mixed)
    asked: רשימת שאלות שכבר נשאלו (למניעת חזרות)
    """
    diff_map  = {"easy": "קלה", "medium": "בינונית", "hard": "קשה"}
    topic     = CATEGORY_PROMPTS.get(cat, "ידע כללי")
    diff_he   = diff_map.get(difficulty, "בינונית")
    avoid_str = ""
    if asked:
        last = asked[-5:]  # מספיק 5 אחרונות
        avoid_str = f"\nאל תחזור על השאלות האלה: {'; '.join(last)}"

    prompt = (
        f"צור שאלת טריוויה על הנושא: {topic}. רמת קושי: {diff_he}.\n"
        f"השאלה חייבת להיות בעברית. היא חייבת להיות שונה לחלוטין מכל שאלה קודמת.{avoid_str}\n"
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
    name     = update.effective_user.first_name or "חבר"
    is_group = update.effective_chat.type in ("group", "supergroup")
    text, keyboard = build_main_menu(name, is_group)
    await update.message.reply_text(text, reply_markup=keyboard)


async def cmd_play(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 *משחק סולו — בחר קטגוריה:*",
        parse_mode="Markdown",
        reply_markup=build_category_keyboard("cat"),
    )


async def cmd_trivia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if get_group_game(ctx.bot_data, chat_id):
        await update.message.reply_text("⏳ כבר יש שאלה פעילה! ענו עליה קודם.")
        return
    await update.message.reply_text(
        "👥 *משחק קבוצתי — בחר קטגוריה:*",
        parse_mode="Markdown",
        reply_markup=build_category_keyboard("gcat"),
    )


async def cmd_score(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.effective_user.id)
    d    = get_user_score(ctx.bot_data, uid)
    s, t = d["score"], d["total"]
    pct  = int(s / t * 100) if t else 0
    _, keyboard = build_main_menu(update.effective_user.first_name or "חבר")
    await update.message.reply_text(
        f"{score_emoji(s)} *הניקוד שלך:*\n\n✅ נכון: {s}/{t}\n📊 הצלחה: {pct}%",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    scores = ctx.bot_data.get("scores", {})
    if not scores:
        await update.message.reply_text("אין ניקודים עדיין!")
        return
    top    = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines  = ["🏆 *טבלת מובילים:*\n"]
    for i, (uid, d) in enumerate(top):
        lines.append(f"{medals[i]} {d.get('name','???')}: {d['score']} ({d['total']} שאלות)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ══════════════════════════════════════════════════════════
#  שליחת שאלה חדשה (סולו) — פונקציה משותפת
# ══════════════════════════════════════════════════════════

async def send_solo_question(query, ctx: ContextTypes.DEFAULT_TYPE, cat: str, diff: str):
    real_cat = resolve_cat(cat)
    asked    = ctx.user_data.get("asked_questions", [])

    await query.edit_message_text(f"⏳ יוצר שאלה ב{cat_label(real_cat)}...")

    try:
        q = await generate_question(real_cat, diff, asked)
    except Exception as e:
        logger.error(f"generate_question error: {e}")
        await query.edit_message_text(
            "❌ שגיאה ביצירת שאלה.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 נסה שוב", callback_data=f"diff:{cat}:{diff}"),
                InlineKeyboardButton("🏠 תפריט", callback_data="menu:home"),
            ]])
        )
        return

    # שמור שאלה + היסטוריה
    asked.append(q["question"])
    if len(asked) > 20:
        asked = asked[-20:]
    ctx.user_data["asked_questions"] = asked
    ctx.user_data["solo_q"]    = q
    ctx.user_data["solo_cat"]  = cat       # המקורי (יכול להיות mixed)
    ctx.user_data["solo_diff"] = diff
    ctx.user_data["solo_real_cat"] = real_cat

    diff_label = DIFFICULTIES.get(diff, diff)
    await query.edit_message_text(
        f"🎮 *{cat_label(real_cat)} | {diff_label}*\n\n{q['question']}",
        parse_mode="Markdown",
        reply_markup=build_answer_keyboard(q["options"], cat, diff, "ans"),
    )

# ══════════════════════════════════════════════════════════
#  Callback router ראשי
# ══════════════════════════════════════════════════════════

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = update.effective_chat.id

    # תשובה כשיש משחק קבוצתי פעיל
    if data.startswith("ans:") and get_group_game(ctx.bot_data, chat_id):
        await handle_group_answer(update, ctx)
        return

    # ── תפריט ראשי ──────────────────────────────────────
    if data.startswith("menu:"):
        action = data.split(":")[1]
        name   = query.from_user.first_name or "חבר"
        is_group = update.effective_chat.type in ("group", "supergroup")

        if action == "home":
            text, keyboard = build_main_menu(name, is_group)
            await query.edit_message_text(text, reply_markup=keyboard)

        elif action == "play":
            await query.edit_message_text(
                "🎮 *משחק סולו — בחר קטגוריה:*",
                parse_mode="Markdown",
                reply_markup=build_category_keyboard("cat"),
            )

        elif action == "trivia":
            if get_group_game(ctx.bot_data, chat_id):
                await query.edit_message_text("⏳ כבר יש שאלה פעילה! ענו עליה קודם.")
                return
            await query.edit_message_text(
                "👥 *משחק קבוצתי — בחר קטגוריה:*",
                parse_mode="Markdown",
                reply_markup=build_category_keyboard("gcat"),
            )

        elif action == "score":
            uid  = str(query.from_user.id)
            d    = get_user_score(ctx.bot_data, uid)
            s, t = d["score"], d["total"]
            pct  = int(s / t * 100) if t else 0
            text, keyboard = build_main_menu(name, is_group)
            await query.edit_message_text(
                f"{score_emoji(s)} *הניקוד שלך:*\n\n✅ נכון: {s}/{t}\n📊 הצלחה: {pct}%",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        elif action == "top":
            scores = ctx.bot_data.get("scores", {})
            if not scores:
                text, keyboard = build_main_menu(name, is_group)
                await query.edit_message_text("אין ניקודים עדיין!", reply_markup=keyboard)
                return
            top    = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)[:5]
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            lines  = ["🏆 *טבלת מובילים:*\n"]
            for i, (uid, d) in enumerate(top):
                lines.append(f"{medals[i]} {d.get('name','???')}: {d['score']} ({d['total']} שאלות)")
            text, keyboard = build_main_menu(name, is_group)
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)

    # ── סולו: בחירת קטגוריה ────────────────────────────
    elif data.startswith("cat:"):
        cat = data.split(":")[1]
        ctx.user_data["solo_cat"] = cat
        await query.edit_message_text(
            f"🎮 *{cat_label(cat)}*\nבחר רמת קושי:",
            parse_mode="Markdown",
            reply_markup=build_difficulty_keyboard(cat, "diff"),
        )

    # ── סולו: בחירת קושי → שאלה ────────────────────────
    elif data.startswith("diff:"):
        parts = data.split(":")
        cat, diff = parts[1], parts[2]
        await send_solo_question(query, ctx, cat, diff)

    # ── סולו: תשובה ────────────────────────────────────
    elif data.startswith("ans:"):
        parts    = data.split(":")
        cat, diff, chosen_str = parts[1], parts[2], parts[3]
        chosen   = int(chosen_str)
        q        = ctx.user_data.get("solo_q")

        if not q:
            name = query.from_user.first_name or "חבר"
            text, keyboard = build_main_menu(name)
            await query.edit_message_text("המשחק פג. בחר מחדש:", reply_markup=keyboard)
            return

        correct      = q["correct"]
        correct_text = q["options"][correct]
        uid          = str(query.from_user.id)
        name         = query.from_user.first_name or "שחקן"
        is_correct   = (chosen == correct)

        update_score(ctx.bot_data, uid, name, is_correct)
        d = get_user_score(ctx.bot_data, uid)
        ctx.user_data.pop("solo_q", None)

        result = "✅ *נכון!*" if is_correct else "❌ *לא נכון*"

        # ← ממשיך אוטומטית לשאלה הבאה
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ שאלה הבאה", callback_data=f"diff:{cat}:{diff}")],
            [InlineKeyboardButton("🗂 קטגוריה אחרת", callback_data="menu:play"),
             InlineKeyboardButton("🏠 תפריט", callback_data="menu:home")],
        ])

        await query.edit_message_text(
            f"{result}\n\n"
            f"✅ תשובה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"📊 ניקוד: {d['score']}/{d['total']}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    # ── חזרה לקטגוריות ──────────────────────────────────
    elif data.startswith("back_cats:"):
        prefix = data.split(":")[1]
        cat_prefix = "cat" if prefix == "diff" else "gcat"
        await query.edit_message_text(
            "🎮 *בחר קטגוריה:*",
            parse_mode="Markdown",
            reply_markup=build_category_keyboard(cat_prefix),
        )

    # ── קבוצתי: בחירת קטגוריה ──────────────────────────
    elif data.startswith("gcat:"):
        cat = data.split(":")[1]
        await query.edit_message_text(
            f"👥 *{cat_label(cat)}*\nבחר רמת קושי:",
            parse_mode="Markdown",
            reply_markup=build_difficulty_keyboard(cat, "gdiff"),
        )

    # ── קבוצתי: בחירת קושי → שאלה ─────────────────────
    elif data.startswith("gdiff:"):
        parts = data.split(":")
        cat, difficulty = parts[1], parts[2]
        chat_id = update.effective_chat.id

        if get_group_game(ctx.bot_data, chat_id):
            return

        real_cat = resolve_cat(cat)
        await query.edit_message_text(f"⏳ יוצר שאלה קבוצתית ב{cat_label(real_cat)}...")

        try:
            q = await generate_question(real_cat, difficulty)
        except Exception as e:
            logger.error(f"group generate_question error: {e}")
            await query.edit_message_text("❌ שגיאה. נסה שוב עם /trivia")
            return

        game = {"q": q, "cat": cat, "real_cat": real_cat, "difficulty": difficulty, "answered": False}
        set_group_game(ctx.bot_data, chat_id, game)

        await query.edit_message_text(
            f"👥 *{cat_label(real_cat)} | {DIFFICULTIES[difficulty]}*\n"
            f"⏱ {GROUP_TIMEOUT} שניות לענות!\n\n"
            f"{q['question']}",
            parse_mode="Markdown",
            reply_markup=build_answer_keyboard(q["options"], cat, difficulty, "ans"),
        )

        async def timeout_reveal():
            await asyncio.sleep(GROUP_TIMEOUT)
            current = get_group_game(ctx.bot_data, chat_id)
            if current and not current.get("answered"):
                set_group_game(ctx.bot_data, chat_id, None)
                correct_text = q["options"][q["correct"]]
                try:
                    await ctx.bot.send_message(
                        chat_id,
                        f"⏰ *הזמן עבר!*\n\n✅ התשובה: *{correct_text}*\n💡 {q.get('explanation','')}\n\nכתבו /trivia לשאלה הבאה!",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

        asyncio.create_task(timeout_reveal())

# ══════════════════════════════════════════════════════════
#  תשובות קבוצתיות
# ══════════════════════════════════════════════════════════

async def handle_group_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    chat_id = update.effective_chat.id

    game = get_group_game(ctx.bot_data, chat_id)
    if not game or game.get("answered"):
        return

    parts      = data.split(":")
    cat, diff, chosen_str = parts[1], parts[2], parts[3]
    chosen     = int(chosen_str)
    q          = game["q"]
    correct    = q["correct"]
    is_correct = (chosen == correct)

    game["answered"] = True
    set_group_game(ctx.bot_data, chat_id, None)

    uid          = str(query.from_user.id)
    name         = query.from_user.first_name or "שחקן"
    correct_text = q["options"][correct]

    update_score(ctx.bot_data, uid, name, is_correct)
    d = get_user_score(ctx.bot_data, uid)

    if is_correct:
        text = (
            f"🏆 *{name} ענה נכון ראשון!*\n\n"
            f"✅ תשובה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"📊 ניקוד של {name}: {d['score']}/{d['total']}\n\n"
            f"כתבו /trivia לשאלה הבאה!"
        )
    else:
        text = (
            f"❌ *{name} ענה לא נכון.*\n\n"
            f"✅ התשובה הנכונה: *{correct_text}*\n"
            f"💡 {q.get('explanation','')}\n\n"
            f"כתבו /trivia לשאלה הבאה!"
        )

    await query.edit_message_text(text, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════
#  הפעלה
# ══════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("play",   cmd_play))
    app.add_handler(CommandHandler("trivia", cmd_trivia))
    app.add_handler(CommandHandler("score",  cmd_score))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("🎯 בוט טריוויה v3 מתחיל...")
    app.run_polling()


if __name__ == "__main__":
    main()
