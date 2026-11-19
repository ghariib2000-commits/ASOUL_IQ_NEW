import tempfile
import unittest
from pathlib import Path

from app.bot.handlers import watchlist_view
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import prices, users, watchlist
from tests.helpers import make_db

USER = 616_161


def _gold_result(value: float) -> ProviderResult:
    return ProviderResult(
        provider_key="gold",
        provider_label="🟡 أسعار الذهب في مصر",
        ok=True,
        fetched_at=now_cairo(),
        quotes=(Quote("GOLD_21", "عيار 21", value, "جنيه/جرام", decimals=2),),
        sources=("api.gold-api.com",),
    )


def _fx_result(value: float) -> ProviderResult:
    return ProviderResult(
        provider_key="fx",
        provider_label="💵 أسعار العملات",
        ok=True,
        fetched_at=now_cairo(),
        quotes=(Quote("USD", "دولار أمريكي", value, "جنيه", decimals=2),),
        sources=("open.er-api.com",),
    )


def _labels(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


class WatchlistViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(USER, "مستخدم اختبار", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_list_points_to_browsing(self) -> None:
        text, keyboard = watchlist_view(USER, self.db)
        self.assertIn("فاضية", text)
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("browse", callbacks)

    def test_groups_items_under_section_headings(self) -> None:
        watchlist.add(USER, "GOLD_21", self.db)
        watchlist.add(USER, "USD", self.db)
        text, _keyboard = watchlist_view(USER, self.db)
        self.assertIn("🟡 الذهب", text)
        self.assertIn("💵 العملات", text)
        self.assertLess(text.index("🟡 الذهب"), text.index("ذهب عيار 21"))

    def test_shows_price_and_change_percentage(self) -> None:
        prices.save_result(_gold_result(5000.0), self.db)
        prices.save_result(_gold_result(5100.0), self.db)
        watchlist.add(USER, "GOLD_21", self.db)

        text, _keyboard = watchlist_view(USER, self.db)

        self.assertIn("5,100.00", text)
        self.assertIn("▲ +2.00%", text)

    def test_shows_down_arrow_for_falling_price(self) -> None:
        prices.save_result(_fx_result(50.0), self.db)
        prices.save_result(_fx_result(47.5), self.db)
        watchlist.add(USER, "USD", self.db)

        text, _keyboard = watchlist_view(USER, self.db)

        self.assertIn("▼ -5.00%", text)

    def test_counter_and_remove_buttons(self) -> None:
        watchlist.add(USER, "GOLD_21", self.db)
        text, keyboard = watchlist_view(USER, self.db)
        self.assertIn(f"1 من {watchlist.MAX_ITEMS}", text)
        self.assertIn("🗑 GOLD_21", _labels(keyboard))

    def test_item_without_price_is_labelled(self) -> None:
        watchlist.add(USER, "GOLD_21", self.db)
        text, _keyboard = watchlist_view(USER, self.db)
        self.assertIn("بدون سعر محدث", text)


if __name__ == "__main__":
    unittest.main()
