"""Runs the Node checks of the page's voice logic (talking over JARVIS), if Node is installed."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side voice checks can't run")
class VoiceInterrupt(unittest.TestCase):
    def test_talking_over_jarvis(self):
        run = subprocess.run(["node", "tests/js/voice_interrupt.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class MenuFit(unittest.TestCase):
    def test_menus_never_run_off_the_top_of_the_screen(self):
        run = subprocess.run(["node", "tests/js/menufit.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class ShowOffMode(unittest.TestCase):
    def test_show_off_phrases_models_and_code(self):
        run = subprocess.run(["node", "tests/js/showoff.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class LookSwitch(unittest.TestCase):
    def test_modern_and_classic_looks(self):
        run = subprocess.run(["node", "tests/js/theme.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class PhoneAssistant(unittest.TestCase):
    def test_the_standalone_assistant(self):
        run = subprocess.run(["node", "tests/js/brain.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class PictureCard(unittest.TestCase):
    def test_the_wall_only_shows_the_pcs_own_pictures(self):
        run = subprocess.run(["node", "tests/js/picture.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class OrbFrameRate(unittest.TestCase):
    def test_the_orbs_do_not_redraw_on_every_screen_refresh(self):
        run = subprocess.run(["node", "tests/js/orb_rate.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class FindMyPhoneVoice(unittest.TestCase):
    def test_find_my_phone_and_the_remote_switch(self):
        run = subprocess.run(["node", "tests/js/phonelink.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)


@unittest.skipUnless(shutil.which("node"), "Node isn't installed, so the browser-side checks can't run")
class RoutinesAndFiles(unittest.TestCase):
    def test_routine_phrases_agree_with_the_pc(self):
        run = subprocess.run(["node", "tests/js/routines.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)

    def test_the_files_card_shows_names_as_text_only(self):
        run = subprocess.run(["node", "tests/js/files.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok   ", run.stdout)
