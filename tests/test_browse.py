import tempfile
import unittest
from pathlib import Path

from app.bot import browse
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import prices, users
from tests.helpers import make_db

USER = 424_242


def _callback_datas(keyboard) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]


class BrowseViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(USER, "مستخدم اختبار", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_menu_lists_every_section_with_counts(self) -> None:
        text, keyboard = browse.browse_menu_view(self.db)
        for section in ("الذهب", "العملات", "أسهم البورصة", "المؤشرات"):
            self.assertIn(section, text)
        datas = _callback_datas(keyboard)
        for section in browse.SECTION_KINDS:
            expected = (
                f"bgl:{section}" if section in browse.GROUPED_SECTIONS else f"br:{section}:0"
            )
            self.assertIn(expected, datas)

    def test_currency_pages_cover_all_currencies_without_repeat(self) -> None:
        seen: list[str] = []
        page = 0
        while True:
            text, keyboard = browse.browse_view("fx", page, USER, self.db)
            codes = [
                data.split(":")[1]
                for data in _callback_datas(keyboard)
                if data.startswith("tg:")
            ]
            self.assertEqual(len(codes), len(set(codes)))
            seen.extend(codes)
            if f"br:fx:{page + 1}" not in _callback_datas(keyboard):
                break
            page += 1
        self.assertEqual(len(seen), 18)
        self.assertEqual(len(set(seen)), 18)

    def test_gold_page_shows_karats_and_estimate_warning(self) -> None:
        text, keyboard = browse.browse_view("gold", 0, USER, self.db)
        self.assertIn("عيار 21", text)
        self.assertIn("عيار 14", text)
        self.assertIn("تقديري", text)
        datas = _callback_datas(keyboard)
        for code in ("GOLD_24", "GOLD_21", "GOLD_18", "GOLD_14", "GOLD_POUND"):
            self.assertIn(f"tg:{code}:gold:0:-", datas)

    def test_page_number_is_clamped(self) -> None:
        text, _ = browse.browse_view("gold", 999, USER, self.db)
        self.assertIn("صفحة <b>1</b>", text)

    def test_shows_price_when_available(self) -> None:
        prices.save_result(
            ProviderResult(
                provider_key="gold",
                provider_label="🟡 أسعار الذهب في مصر",
                ok=True,
                fetched_at=now_cairo(),
                quotes=(Quote("GOLD_21", "عيار 21", 5450.5, "جنيه/جرام", decimals=2),),
                sources=("api.gold-api.com",),
            ),
            self.db,
        )
        text, _ = browse.browse_view("gold", 0, USER, self.db)
        self.assertIn("5,450.50", text)

    def test_toggle_adds_then_removes(self) -> None:
        self.assertEqual(browse.toggle(USER, "GOLD_21", self.db), "added")
        self.assertTrue(browse.watchlist.contains(USER, "GOLD_21", self.db))
        self.assertEqual(browse.toggle(USER, "GOLD_21", self.db), "removed")
        self.assertFalse(browse.watchlist.contains(USER, "GOLD_21", self.db))

    def test_toggle_unknown_asset_reports_missing(self) -> None:
        self.assertEqual(browse.toggle(USER, "NOPE", self.db), "missing")

    def _seed_stocks(self, names: dict[str, str]) -> None:
        prices.save_result(
            ProviderResult(
                provider_key="egx",
                provider_label="📈 البورصة المصرية",
                ok=True,
                fetched_at=now_cairo(),
                quotes=tuple(
                    Quote(code=code, label=label, value=10.0, unit="جنيه", decimals=2)
                    for code, label in names.items()
                ),
                sources=("scanner.tradingview.com",),
                meta={"auto_register": True, "register_kind": "equity"},
            ),
            self.db,
        )

    def test_groups_cover_every_stock_once(self) -> None:
        self._seed_stocks({"ABUK": "Abou Kir Fertilizers", "COMI": "Commercial Bank"})
        groups = browse.letter_groups("egx", self.db)
        self.assertEqual(sum(count for _letter, count in groups), 2)
        letters = [letter for letter, _count in groups]
        self.assertEqual(len(letters), len(set(letters)))

    def test_group_page_only_shows_its_letter(self) -> None:
        self._seed_stocks({"COMI": "Commercial Bank", "MILS": "Middle Egypt Mills"})
        groups = browse.letter_groups("egx", self.db)
        self.assertEqual(len(groups), 2)
        index = groups.index(("ب", 1))
        text, keyboard = browse.group_view("egx", index, 0, USER, self.db)
        self.assertIn("COMI", text)
        self.assertNotIn("MILS", text)
        self.assertIn("حرف ب", text)
        datas = _callback_datas(keyboard)
        self.assertIn(f"bg:egx:{index}:0", datas)
        self.assertTrue(any(data.startswith("tg:COMI:egx:0:") for data in datas))

    def test_groups_view_has_one_button_per_letter(self) -> None:
        self._seed_stocks({"ABUK": "Abou Kir Fertilizers", "COMI": "Commercial Bank"})
        text, keyboard = browse.groups_view("egx", self.db)
        self.assertIn("شركة", text)
        group_buttons = [d for d in _callback_datas(keyboard) if d.startswith("bg:")]
        self.assertEqual(len(group_buttons), len(browse.letter_groups("egx", self.db)))

    def test_group_view_clamps_out_of_range_index(self) -> None:
        self._seed_stocks({"ABUK": "Abou Kir Fertilizers"})
        text, _keyboard = browse.group_view("egx", 99, 0, USER, self.db)
        self.assertIn("ABUK", text)

    def test_followed_item_marked_with_check(self) -> None:
        browse.toggle(USER, "AED", self.db)
        _text, keyboard = browse.browse_view("fx", 0, USER, self.db)
        labels = [
            button.text for row in keyboard.inline_keyboard for button in row
        ]
        self.assertTrue(any(label.startswith("✅") for label in labels))
        self.assertTrue(any(label.startswith("➕") for label in labels))


if __name__ == "__main__":
    unittest.main()
