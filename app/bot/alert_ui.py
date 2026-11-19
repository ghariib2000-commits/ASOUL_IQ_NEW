"""شاشة إنشاء تنبيه من داخل قوائم التصفح.

المستخدم يضغط 🔔 جنب أي أصل، فيفتح له خيارات جاهزة:
ارتفاع/انخفاض 2% أو 5%، أو سعر معيّن يكتبه بأمر واحد.
لا تكرار ولا حاجة لحفظ صيغة الأوامر.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services import alerts, assets, prices

PERCENT_PRESETS = (2, 5)


def _back_callback(origin: tuple[str, int, str]) -> str:
    section, page, group = origin
    return f"bg:{section}:{group}:{page}" if group.isdigit() else f"br:{section}:{page}"


def _price_text(latest) -> str:
    if latest is None:
        return "السعر الحالي غير متاح بعد"
    return f"{float(latest['price']):,.2f}"


def alert_screen(
    code: str,
    telegram_id: int,
    origin: tuple[str, int, str],
    note: str = "",
    db_path: str | Path | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """شاشة تنبيه أصل واحد مع أزرار جاهزة."""
    asset = assets.get_asset(code, db_path)
    back = _back_callback(origin)
    if asset is None:
        return (
            "⚠️ الأصل غير متاح.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=back)]]),
        )

    section, page, group = origin
    latest = prices.latest(asset["code"], db_path)
    name = escape(str(asset["name_ar"]))
    unit = escape(str(asset["unit"] or "جنيه"))

    lines = [f"🔔 <b>تنبيه: {name}</b>", ""]
    if note:
        lines.extend([note, ""])
    lines.append(f"السعر الحالي: <b>{_price_text(latest)}</b> {unit}")
    lines.append("")
    lines.append("اختار نوع التنبيه — هيوصلك إشعار في تيليجرام لما الشرط يتحقق:")
    lines.append("")

    mine = [
        rule
        for rule in alerts.list_rules(telegram_id, db_path)
        if rule["asset_code"] == asset["code"]
    ]
    if mine:
        lines.append("<b>تنبيهاتك الحالية على الأصل ده:</b>")
        for rule in mine:
            suffix = "%" if rule["rule_type"] in (alerts.RULE_PCT_UP, alerts.RULE_PCT_DOWN) else f" {unit}"
            lines.append(
                f"• #{rule['id']} {alerts.RULE_LABELS[rule['rule_type']]} "
                f"{rule['threshold']:,.2f}{suffix}"
            )
    else:
        lines.append("<i>مفيش تنبيهات على الأصل ده لحد الآن.</i>")

    def action(token: str) -> str:
        return f"aa:{asset['code']}:{token}:{section}:{page}:{group}"

    rows: list[list[InlineKeyboardButton]] = []
    for preset in PERCENT_PRESETS:
        rows.append(
            [
                InlineKeyboardButton(
                    f"⬆️ يرتفع {preset}%", callback_data=action(f"u{preset}")
                ),
                InlineKeyboardButton(
                    f"⬇️ ينخفض {preset}%", callback_data=action(f"d{preset}")
                ),
            ]
        )
    rows.append([InlineKeyboardButton("🎯 سعر معين أكتبه", callback_data=action("manual"))])
    rows.append(
        [
            InlineKeyboardButton("🔔 تنبيهاتي", callback_data="menu_alerts"),
            InlineKeyboardButton("🔙 رجوع", callback_data=back),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def manual_hint(code: str, db_path: str | Path | None = None) -> str:
    """أمر جاهز للنسخ لتنبيه بسعر محدد."""
    latest = prices.latest(code, db_path)
    if latest is None:
        example = "55"
    else:
        example = f"{float(latest['price']):,.2f}".replace(",", "")
    return (
        "🎯 <b>تنبيه بسعر معين</b>\n\n"
        "انسخ السطر ده وعدّل الرقم:\n"
        f"<code>/alert {code} above {example}</code>\n"
        f"<code>/alert {code} below {example}</code>\n\n"
        "• <code>above</code> = لما السعر يوصل أو يعدّي الرقم\n"
        "• <code>below</code> = لما السعر ينزل للرقم أو تحته"
    )


def apply_action(
    telegram_id: int,
    code: str,
    token: str,
    db_path: str | Path | None = None,
) -> tuple[str, str]:
    """ينشئ تنبيه نسبة من زر جاهز. يرجع (حالة، نص تأكيد)."""
    if not token or token[0] not in "ud" or not token[1:].isdigit():
        return "invalid", "⚠️ اختيار غير معروف."
    percent = float(token[1:])
    rule_type = alerts.RULE_PCT_UP if token[0] == "u" else alerts.RULE_PCT_DOWN
    rule_id = alerts.add_rule(telegram_id, code, rule_type, percent, db_path)
    if rule_id is None:
        return "failed", (
            "⚠️ التنبيه موجود بالفعل، أو وصلت للحد الأقصى، أو الأصل غير متاح."
        )
    direction = "يرتفع" if token[0] == "u" else "ينخفض"
    return "created", f"✅ تم إنشاء تنبيه #{rule_id}: {direction} {percent:g}%"
