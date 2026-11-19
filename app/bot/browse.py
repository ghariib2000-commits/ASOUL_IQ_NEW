"""تصفح الأسواق على شكل أقسام وقوائم بدل حفظ الأوامر.

المسار: القائمة الرئيسية ← قسم ← (للأسهم) مجموعة حروف ← صفحة ← متابعة/إلغاء.

كل أصل له زر واحد: ➕ يضيفه لقائمة المتابعة و✅ يزيله، وكل ضغطة تعيد رسم
نفس الصفحة — فالمستخدم يشوف السعر ويقرر في نفس الشاشة.

كل الدوال متزامنة (قاعدة بيانات) وتُستدعى من Thread عبر asyncio.to_thread
حتى لا يتجمد البوت أثناء قراءة SQLite.
"""

from __future__ import annotations

import math
from html import escape
from pathlib import Path
from typing import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import assets, prices, watchlist

PAGE_SIZE = 8

# (مفتاح القسم، الاسم المعروض، نوع الأصل في جدول assets)
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("gold", "🟡 الذهب والصاغة", "commodity"),
    ("fx", "💵 العملات", "currency"),
    ("egx", "🏦 أسهم البورصة", "equity"),
    ("idx", "📉 المؤشرات", "index"),
)

SECTION_LABELS = {key: label for key, label, _ in SECTIONS}
SECTION_KINDS = {key: kind for key, _, kind in SECTIONS}
# قسم المؤشرات يُغذَّى من نفس مزود البورصة.
SECTION_PROVIDERS = {"gold": "gold", "fx": "fx", "egx": "egx", "idx": "egx"}
# الأقسام الكبيرة فقط تُجمَّع بالحروف.
GROUPED_SECTIONS = frozenset({"egx"})

GOLD_NOTE = (
    "⚠️ <i>سعر تقديري محسوب من سعر الأونصة العالمي وسعر الدولار، "
    "وقد يختلف عن سعر الصاغة. ليست عرضًا من صاغة.</i>"
)

GOLD_SOURCES = "<i>🔗 المصدر: api.gold-api.com + open.er-api.com</i>"

# ترتيب أبجدي عربي لحروف البداية (الحروف غير الموجودة تذهب للنهاية).
ARABIC_ORDER = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
LETTER_ALIASES = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"}
OTHER_GROUP = "#"


def _short(name: str, limit: int = 24) -> str:
    text = (name or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _page_count(total: int) -> int:
    return max(1, math.ceil(total / PAGE_SIZE))


def section_items(section: str, db_path: str | Path | None = None) -> list:
    kind = SECTION_KINDS.get(section)
    if kind is None:
        return []
    return assets.list_assets(kind, db_path)


def first_letter(name: str) -> str:
    """حرف التجميع لاسم عربي.

    نستبعد "ال" التعريف حتى لا يتكدس أغلب الشركات تحت حرف الألف،
    ونوحّد الهمزات والألف المقصورة.
    """
    text = (name or "").strip()
    if not text:
        return OTHER_GROUP
    if text.startswith("ال") and len(text) > 3:
        text = text[2:].strip() or text
    char = text[0]
    if "\u0600" <= char <= "\u06ff":
        return LETTER_ALIASES.get(char, char)
    return OTHER_GROUP


def letter_groups(section: str, db_path: str | Path | None = None) -> list[tuple[str, int]]:
    """(الحرف، عدد الأصول) مرتبة أبجديًا — تُستخدم لقسم الأسهم."""
    counts: dict[str, int] = {}
    for row in section_items(section, db_path):
        letter = first_letter(str(row["name_ar"]))
        counts[letter] = counts.get(letter, 0) + 1

    def sort_key(letter: str) -> tuple[int, str]:
        if letter == OTHER_GROUP:
            return (len(ARABIC_ORDER) + 1, "")
        return (ARABIC_ORDER.index(letter) if letter in ARABIC_ORDER else len(ARABIC_ORDER), letter)

    return sorted(counts.items(), key=lambda item: sort_key(item[0]))


def _items_for_letter(
    section: str, letter: str, db_path: str | Path | None = None
) -> list:
    return [
        row
        for row in section_items(section, db_path)
        if first_letter(str(row["name_ar"])) == letter
    ]


def browse_menu_view(db_path: str | Path | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """قائمة الأقسام مع عدد الأصول المتاح في كل واحد."""
    lines = [
        "🔍 <b>تصفح الأسواق</b>",
        "",
        "اختار القسم اللي يعجبك، وبعدها اضغط على أي أصل:",
        "➕ يضيفه لقائمتك ⭐ — و✅ يزيله.",
        "",
    ]
    buttons = []
    for key, label, _kind in SECTIONS:
        total = len(section_items(key, db_path))
        lines.append(f"• {label}: <b>{total}</b> أصول")
        target = f"bgl:{key}" if key in GROUPED_SECTIONS else f"br:{key}:0"
        buttons.append(InlineKeyboardButton(f"{label} ({total})", callback_data=target))

    keyboard = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton("⭐ قائتي", callback_data="menu_watchlist")])
    keyboard.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def groups_view(
    section: str, db_path: str | Path | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    """مجموعات الحروف لقسم كبير (الأسهم)."""
    groups = letter_groups(section, db_path)
    label = SECTION_LABELS.get(section, section)
    if not groups:
        return browse_view(section, 0, None, db_path)

    lines = [
        f"<b>{label}</b>",
        "",
        f"الشركات متجمعة بالحرف — <b>{sum(count for _, count in groups)}</b> شركة.",
        "اختار حرف تشوف شركاته وتتابع اللي تحبه:",
        "",
    ]
    buttons = [
        InlineKeyboardButton(f"{letter} ({count})", callback_data=f"bg:{section}:{index}:0")
        for index, (letter, count) in enumerate(groups)
    ]
    keyboard = [buttons[index : index + 4] for index in range(0, len(buttons), 4)]
    keyboard.append(
        [
            InlineKeyboardButton("🔄 كل الشركات", callback_data=f"br:{section}:0"),
            InlineKeyboardButton("🔙 الأقسام", callback_data="browse"),
        ]
    )
    keyboard.append([InlineKeyboardButton("⭐ قائتي", callback_data="menu_watchlist")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def _price_line(row, price_row) -> str:
    name = escape(str(row["name_ar"]))
    code = escape(str(row["code"]))
    if price_row is None:
        return f"• <b>{name}</b> (<code>{code}</code>): بدون سعر بعد"
    value = float(price_row["price"])
    unit = escape(str(row["unit"] or "جنيه"))
    line = f"• <b>{name}</b> (<code>{code}</code>): {value:,.2f} {unit}"
    if prices.is_stale(price_row):
        line += " ⚠️"
    return line


def _render_page(
    section: str,
    items: Sequence,
    page: int,
    telegram_id: int | None,
    db_path: str | Path | None,
    group_index: int | None = None,
    group_label: str = "",
) -> tuple[str, InlineKeyboardMarkup]:
    """يرسم صفحة واحدة: الأسعار في النص وأزرار ➕/✅ تحتها."""
    label = SECTION_LABELS.get(section, section)
    title = f"{label} — حرف {group_label}" if group_label else label
    pages = _page_count(len(items))
    page = min(max(page, 0), pages - 1)
    window = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    group_tag = "-" if group_index is None else str(group_index)

    if not items:
        return (
            f"{label}\n\nمفيش أصول مسجلة في القسم ده لحد الآن.",
            InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 تحديث الأسعار", callback_data=f"brr:{section}")],
                    [InlineKeyboardButton("🔙 للقوائم", callback_data="browse")],
                    [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
                ]
            ),
        )

    price_map = prices.latest_for([row["code"] for row in window], db_path)

    lines = [f"<b>{title}</b>", ""]
    if section == "gold":
        lines.extend([GOLD_NOTE, ""])
    unit_word = "شركة" if section == "egx" else "أصول"
    lines.append(
        f"صفحة <b>{page + 1}</b> من <b>{pages}</b> — إجمالي {len(items)} {unit_word}"
    )
    lines.append("")

    rows: list[list[InlineKeyboardButton]] = []
    for row in window:
        lines.append(_price_line(row, price_map.get(row["code"])))
        followed = (
            watchlist.contains(telegram_id, row["code"], db_path)
            if telegram_id is not None
            else False
        )
        mark = "✅" if followed else "➕"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark} {_short(str(row['name_ar']))}",
                    callback_data=f"tg:{row['code']}:{section}:{page}:{group_tag}",
                ),
                InlineKeyboardButton(
                    "🔔", callback_data=f"al:{row['code']}:{section}:{page}:{group_tag}"
                ),
            ]
        )

    if section == "gold":
        lines.extend(["", GOLD_SOURCES])
    if section in ("gold", "fx"):
        lines.extend(["", "<i>اضغط على الاسم لمتابعة العيار/العملة في قائمتك.</i>"])

    def page_callback(target: int) -> str:
        if group_index is None:
            return f"br:{section}:{target}"
        return f"bg:{section}:{group_index}:{target}"

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("⬅️ السابق", callback_data=page_callback(page - 1))
        )
    nav.append(
        InlineKeyboardButton(f"{page + 1}/{pages}", callback_data=page_callback(page))
    )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton("التالي ➡️", callback_data=page_callback(page + 1))
        )
    rows.append(nav)

    back_row = []
    if section in GROUPED_SECTIONS:
        back_row.append(InlineKeyboardButton("🔤 الحروف", callback_data=f"bgl:{section}"))
    back_row.append(InlineKeyboardButton("🔄 تحديث", callback_data=f"brr:{section}:{page}"))
    back_row.append(InlineKeyboardButton("🔙 الأقسام", callback_data="browse"))
    rows.append(back_row)
    rows.append([InlineKeyboardButton("⭐ قائتي", callback_data="menu_watchlist")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


def browse_view(
    section: str,
    page: int = 0,
    telegram_id: int | None = None,
    db_path: str | Path | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """صفحة من قسم كامل (بدون تجميع)."""
    if section not in SECTION_KINDS:
        section = "gold"
    return _render_page(section, section_items(section, db_path), page, telegram_id, db_path)


def group_view(
    section: str,
    group_index: int,
    page: int = 0,
    telegram_id: int | None = None,
    db_path: str | Path | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """صفحة من مجموعة حرف داخل قسم كبير."""
    groups = letter_groups(section, db_path)
    if not groups:
        return browse_view(section, page, telegram_id, db_path)
    index = min(max(group_index, 0), len(groups) - 1)
    letter, _count = groups[index]
    items = _items_for_letter(section, letter, db_path)
    return _render_page(section, items, page, telegram_id, db_path, index, letter)


def toggle(telegram_id: int, code: str, db_path: str | Path | None = None) -> str:
    """يضيف أو يزيل أصلًا. يرجع added / removed / full / missing."""
    if watchlist.contains(telegram_id, code, db_path):
        return "removed" if watchlist.remove(telegram_id, code, db_path) else "missing"
    if assets.get_asset(code, db_path) is None:
        return "missing"
    return "added" if watchlist.add(telegram_id, code, db_path) else "full"
