"""The Start menu shortcut and its icon: the icon is a real .ico, and the scripts only add or remove JARVIS's own shortcut."""
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Icon(unittest.TestCase):
    def setUp(self):
        self.data = (ROOT / "assets" / "JARVIS.ico").read_bytes()

    def test_it_is_a_windows_icon_with_the_usual_sizes(self):
        reserved, kind, count = struct.unpack("<HHH", self.data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        sizes = []
        for i in range(count):
            w, h, _, _, planes, bpp, size, offset = struct.unpack("<BBBBHHII", self.data[6 + 16 * i:22 + 16 * i])
            sizes.append(w or 256)
            self.assertEqual(w, h)
            self.assertEqual((planes, bpp), (1, 32))
            blob = self.data[offset:offset + size]
            self.assertEqual(blob[:8], b"\x89PNG\r\n\x1a\n")                          # each size is a PNG inside the icon
            pw, ph = struct.unpack(">II", blob[16:24])
            self.assertEqual((pw, ph), (w or 256, h or 256))
        self.assertEqual(sorted(sizes), [16, 24, 32, 48, 64, 128, 256])

    def test_it_is_small(self):
        self.assertLess(len(self.data), 200_000)


class Scripts(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_the_shortcut_starts_jarvis_with_its_icon(self):
        bat = self.read("install_shortcut.bat")
        self.assertIn("'JARVIS.bat'", bat)
        self.assertIn(r"assets\JARVIS.ico", bat)
        self.assertIn("GetFolderPath('Programs')", bat)                              # the Start menu, wherever Windows keeps it
        self.assertIn("GetFolderPath('Desktop')", bat)                               # optional, only when asked for
        self.assertIn("WindowStyle = 7", bat)                                        # started minimised: no console window on screen

    def test_only_jarvis_own_shortcut_is_touched(self):
        for name in ("install_shortcut.bat", "remove_shortcut.bat"):
            bat = self.read(name)
            for banned in ("reg add", "reg delete", "Set-ItemProperty", "schtasks", "netsh", "Remove-Item -Recurse", "rmdir", "del /s"):
                self.assertNotIn(banned, bat, f"{name}: {banned}")
        remove = self.read("remove_shortcut.bat")
        self.assertEqual(re.findall(r"Join-Path \$p '([^']+)'", remove), ["JARVIS.lnk"])
        self.assertEqual(len(re.findall(r"Remove-Item", remove)), 1)

    def test_the_desktop_one_is_not_made_unless_asked(self):
        bat = self.read("install_shortcut.bat")
        self.assertIn('if /i "%%A"=="desktop" set "WANT_DESKTOP=1"', bat)
        self.assertIn("-eq '1'", bat)

    def test_every_script_it_points_at_exists(self):
        self.assertTrue((ROOT / "JARVIS.bat").exists())
        self.assertTrue((ROOT / "assets" / "JARVIS.ico").exists())
        self.assertTrue((ROOT / "tools" / "make_icon.py").exists())


if __name__ == "__main__":
    unittest.main()
