"""时间能力：读写时钟、ISO 解析、cron/once 推算与漏跑槽位。"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from ai_new.modules.agent_common.clock.private import _clock as c  # noqa: E402


class Api:
    def __init__(self):
        self.rows = []

    def register(self, route, fn, desc, module=None):
        self.rows.append((route, fn, desc, module))


class Ctx:
    def __init__(self):
        self.api = Api()


class ClockTest(unittest.TestCase):
    def test_basic_clock(self):
        self.assertIn("ts", c.now())
        self.assertTrue(c.iso(0).endswith("Z"))
        self.assertTrue(c.iso().endswith("Z"))
        self.assertTrue(c.parse("2020-01-01T00:00:00+00:00")["ok"])
        self.assertEqual(c.parse("bad")["code"], "bad_time")
        self.assertEqual(c.parse(None)["code"], "bad_time")
        self.assertEqual(c.sleep(-1), {"slept": -1.0})
        self.assertEqual(c.sleep(None), {"slept": 0.0})
        self.assertIn("ts", c.monotonic())
        ctx = Ctx()
        self.assertTrue(c.setup(ctx))
        self.assertEqual(len(ctx.api.rows), 3)

    def test_since(self):
        self.assertFalse(c.since({})["ok"])
        self.assertFalse(c.since({"iso": "bad"})["ok"])
        aware = c.since({"iso": "2000-01-01T00:00:00+00:00"})
        self.assertTrue(aware["ok"])
        self.assertGreater(aware["seconds"], 0)
        naive = c.since({"iso": "2000-01-01T00:00:00"})
        self.assertTrue(naive["ok"])

    def test_load_tz(self):
        self.assertIsNone(c._load_tz(""))
        self.assertIsNotNone(c._load_tz("Asia/Shanghai"))
        self.assertIsNone(c._load_tz("No/Such"))
        with mock.patch.object(c, "ZoneInfo", None):
            fixed = c._load_tz("Asia/Shanghai")
            self.assertEqual(fixed.utcoffset(None).total_seconds(), 8 * 3600)
            self.assertIsNone(c._load_tz("No/Such"))

    def test_zoneinfo_fallback_import(self):
        with mock.patch.dict(sys.modules, {"zoneinfo": None, "backports": None,
                                           "backports.zoneinfo": None}):
            reloaded = importlib.reload(c)
            self.assertIsNone(reloaded.ZoneInfo)
        importlib.reload(c)

    def test_cron_field(self):
        self.assertEqual(c._cron_field("*/5", 0, 59), set(range(0, 60, 5)))
        self.assertEqual(c._cron_field("1,3", 0, 59), {1, 3})
        self.assertEqual(c._cron_field("2-4", 0, 59), {2, 3, 4})
        self.assertIsNone(c._cron_field("", 0, 59))
        self.assertIsNone(c._cron_field("*/x", 0, 59))
        self.assertIsNone(c._cron_field("a-b", 0, 59))
        self.assertIsNone(c._cron_field("x", 0, 59))
        self.assertIsNone(c._cron_field("0-60", 0, 59))
        self.assertIsNone(c._cron_field("5-1", 0, 59))
        self.assertIsNone(c._cron_field("*/0", 0, 59))

    def test_cron_parse_match(self):
        self.assertIsNone(c._parse_cron("bad"))
        fields = c._parse_cron("0 12 1 1 1")
        self.assertEqual(fields["minute"], {0})
        bad = c._parse_cron("x 1 1 1 1")
        self.assertIsNone(bad)
        dt = c.datetime.datetime(2024, 1, 1, 12, 0, tzinfo=c.datetime.timezone.utc)
        self.assertTrue(c._cron_match(c._parse_cron("* * * * *"), dt))
        for expr in ("1 * * * *", "* 1 * * *", "* * 2 * *", "* * * 2 *",
                     "* * * * 2"):
            self.assertFalse(c._cron_match(c._parse_cron(expr), dt))
        self.assertEqual(c._slot_of(0, c.datetime.timezone.utc), "1970-01-01T00:00")

    def test_parse_once(self):
        self.assertEqual(c._parse_once("", None)["code"], "bad_time")
        self.assertEqual(c._parse_once("bad", None)["code"], "bad_time")
        self.assertEqual(c._parse_once("2020-01-01T00:00:00", None)["code"], "bad_tz")
        aware = c._parse_once("2020-01-01T00:00:00Z", None)
        self.assertIn("ts", aware)
        naive = c._parse_once("2020-01-01T00:00:00", c.datetime.timezone.utc)
        self.assertIn("ts", naive)

    def test_schedule_once_and_errors(self):
        self.assertEqual(c.schedule_next({"kind": "x"})["code"], "bad_kind")
        self.assertEqual(c.schedule_next({"kind": "once", "expr": ""})["code"], "bad_time")
        self.assertEqual(c.schedule_next({"kind": "once", "expr": "2020-01-01T00:00:00",
                                          "tz": "No/Such", "after": 0})["code"], "bad_tz")
        self.assertEqual(c.schedule_next({"kind": "once", "expr": "2020-01-01T00:00:00Z",
                                          "after": 1577836795, "min_interval_s": 10})["code"],
                         "interval_too_short")
        ok = c.schedule_next({"kind": "once", "expr": "2020-01-01T00:00:00Z",
                              "after": 0})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["slot"], "2020-01-01T00:00")

    def test_schedule_cron(self):
        self.assertEqual(c.schedule_next({"kind": "cron", "expr": "bad"})["code"],
                         "bad_cron")
        self.assertEqual(c.schedule_next({"kind": "cron", "expr": "* * * * *",
                                          "tz": "No/Such"})["code"], "bad_tz")
        ok = c.schedule_next({"kind": "cron", "expr": "* * * * *", "after": 0})
        self.assertEqual(ok["ts"], 0)
        self.assertEqual(c.schedule_next({"kind": "cron", "expr": "0 0 31 2 *",
                                          "after": 0})["code"], "bad_cron")

    def test_due_slots(self):
        self.assertEqual(c.due_slots({"kind": "x"})["code"], "bad_kind")
        self.assertEqual(c.due_slots({"kind": "once", "expr": ""})["code"], "bad_time")
        self.assertEqual(c.due_slots({"kind": "once", "expr": "2020-01-01T00:00:00Z",
                                      "now": 1})["slots"], [])
        self.assertEqual(c.due_slots({"kind": "once", "expr": "2020-01-01T00:00:00Z",
                                      "now": 1577836801})["slots"],
                         ["2020-01-01T00:00"])
        self.assertEqual(c.due_slots({"kind": "cron", "expr": "bad"})["code"],
                         "bad_cron")
        self.assertEqual(c.due_slots({"kind": "cron", "expr": "* * * * *",
                                      "tz": "No/Such"})["code"], "bad_tz")
        full = c.due_slots({"kind": "cron", "expr": "* * * * *", "now": 180})
        self.assertEqual(len(full["slots"]), 4)
        limited = c.due_slots({"kind": "cron", "expr": "* * * * *", "now": 180,
                               "limit": 2})
        self.assertEqual(len(limited["slots"]), 2)
        self.assertFalse(c.due_slots({"kind": "cron", "expr": "* * * * *",
                                      "after": 60, "now": 10})["slots"])
        mixed = c.due_slots({"kind": "cron", "expr": "0 0 1 1 *", "now": 120})
        self.assertEqual(len(mixed["slots"]), 1)
        exhausted = c.due_slots({"kind": "cron", "expr": "0 0 31 2 *",
                                 "now": 527040 * 60})
        self.assertEqual(exhausted["slots"], [])


if __name__ == "__main__":
    unittest.main()
