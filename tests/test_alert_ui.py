import tempfile
import unittest
from pathlib import Path

from app.bot import alert_ui, browse
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import alerts, prices, users
from tests.helpers import make_db

USER = 515_151
ORIGIN = ("gold", 0, "-")


def _datas(keyboard) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]


class AlertScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(USER, "مستخدم اختبار", self.db)
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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_screen_shows_current_price_and_presets(self) -> None:
        text, keyboard = alert_ui.alert_screen("GOLD_21", USER, ORIGIN, db_path=self.db)
        self.assertIn("5,450.50", text)
        datas = _datas(keyboard)
        for token in ("u2", "d2", "u5", "d5", "manual"):
            self.assertIn(f"aa:GOLD_21:{token}:gold:0:-", datas)
        self.assertIn("br:gold:0", datas)

    def test_screen_returns_to_letter_group_when_opened_from_it(self) -> None:
        _text, keyboard = alert_ui.alert_screen("GOLD_21", USER, ("egx", 3, "7"), db_path=self.db)
        self.assertIn("bg:egx:7:3", _datas(keyboard))

    def test_preset_creates_percentage_rule(self) -> None:
        status, message = alert_ui.apply_action(USER, "GOLD_21", "u2", self.db)
        self.assertEqual(status, "created")
        self.assertIn("2%", message)
        rules = alerts.list_rules(USER, self.db)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["rule_type"], alerts.RULE_PCT_UP)
        self.assertEqual(rules[0]["threshold"], 2)

    def test_down_preset_creates_down_rule(self) -> None:
        alert_ui.apply_action(USER, "GOLD_21", "d5", self.db)
        rule = alerts.list_rules(USER, self.db)[0]
        self.assertEqual(rule["rule_type"], alerts.RULE_PCT_DOWN)
        self.assertEqual(rule["threshold"], 5)

    def test_duplicate_preset_is_reported_not_duplicated(self) -> None:
        alert_ui.apply_action(USER, "GOLD_21", "u2", self.db)
        status, _message = alert_ui.apply_action(USER, "GOLD_21", "u2", self.db)
        self.assertEqual(status, "failed")
        self.assertEqual(len(alerts.list_rules(USER, self.db)), 1)

    def test_unknown_token_is_rejected(self) -> None:
        status, _message = alert_ui.apply_action(USER, "GOLD_21", "zz", self.db)
        self.assertEqual(status, "invalid")

    def test_manual_hint_has_copyable_command(self) -> None:
        hint = alert_ui.manual_hint("GOLD_21", self.db)
        self.assertIn("/alert GOLD_21 above 5450.5", hint)
        self.assertIn("/alert GOLD_21 below 5450.5", hint)

    def test_alert_screen_lists_existing_rules(self) -> None:
        alert_ui.apply_action(USER, "GOLD_21", "u2", self.db)
        text, _keyboard = alert_ui.alert_screen("GOLD_21", USER, ORIGIN, db_path=self.db)
        self.assertIn("تنبيهاتك الحالية", text)
        self.assertIn("#1", text)


class BrowseAlertButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(USER, "مستخدم اختبار", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_every_item_has_an_alert_button(self) -> None:
        _text, keyboard = browse.browse_view("gold", 0, USER, self.db)
        datas = _datas(keyboard)
        alert_buttons = [data for data in datas if data.startswith("al:")]
        self.assertEqual(len(alert_buttons), 5)
        self.assertIn("al:GOLD_21:gold:0:-", alert_buttons)


if __name__ == "__main__":
    unittest.main()
