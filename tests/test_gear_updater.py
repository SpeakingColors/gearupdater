import sys, unittest, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gear_updater"))
import sysex, gear_updater


class T(unittest.TestCase):
    def test_good(self):
        r = sysex.check(bytes([0xF0, 1, 2, 3, 0xF7, 0xF0, 9, 0xF7]))
        self.assertTrue(r.ok); self.assertEqual(r.messages, 2); self.assertEqual(r.largest, 5)

    def test_bad(self):
        for data in (b"", bytes([0xF0, 1, 2]), bytes([1, 2, 0xF7]), bytes([0xF0, 0xF0, 0xF7]), bytes([0xF0, 0x90, 0xF7])):
            self.assertFalse(sysex.check(data).ok, data)

    def test_amidi(self):
        t = "Dir Device    Name\nIO  hw:2,0,0  FM-1 MIDI 1\nI   hw:3,0,0  Other\n"
        p = gear_updater.parse_amidi(t)
        self.assertEqual([x["id"] for x in p], ["hw:2,0,0", "hw:3,0,0"])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "a.syx"); open(f, "wb").write(bytes([0xF0, 1, 0xF7]))
            self.assertEqual(gear_updater.main(["dry-run", f]), 0)
            self.assertEqual(gear_updater.main(["dry-run", f, "--sha256", "00"]), 2)
            self.assertEqual(gear_updater.main(["dry-run", os.path.join(d, "nope.syx")]), 1)


if __name__ == "__main__":
    unittest.main()
