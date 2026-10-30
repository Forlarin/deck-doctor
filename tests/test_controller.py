"""Controller layout check, using the real Assassin's Creed Mirage layout where A sent RB."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor.controller import check_layout, face_button_problems  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mirage_controller_neptune.vdf")
APPID = 3035570
BROKEN_A = '"binding"\t\t"xinput_button SHOULDER_RIGHT, , "'
FIXED_A = '"binding"\t\t"xinput_button A, , "'


def mirage(fixed=False):
    with open(FIXTURE) as f:
        text = f.read()
    return text.replace(BROKEN_A, FIXED_A, 1) if fixed else text


class Layout(unittest.TestCase):
    def test_mirage_a_sends_rb(self):
        self.assertEqual(face_button_problems(mirage()), {"missing": ["A"], "remapped": {"A": "SHOULDER_RIGHT"}})

    def test_fixed_layout_is_fine(self):
        self.assertIsNone(face_button_problems(mirage(fixed=True)))


class WhichLayout(unittest.TestCase):
    """A fake Steam folder: the Deck's own config set, the generic Deck one, and a DualSense."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.cfg = os.path.join(self.root, "steamapps", "common", "Steam Controller Configs", "123", "config")
        os.makedirs(os.path.join(self.cfg, str(APPID)))
        shutil.copy(FIXTURE, os.path.join(self.cfg, str(APPID), "controller_neptune.vdf"))
        self.write("preferences_FYZZ0000.vdf", '"controller_mappings"\n{\n\t"name"\t\t"Steam Deck Controller"\n}\n')
        self.write("preferences_DS5000.vdf", '"controller_mappings"\n{\n\t"name"\t\t"DualSense Wireless Controller"\n}\n')
        self.write("configset_controller_neptune.vdf", self.entry('"autosave"\t\t"1"'))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        with open(os.path.join(self.cfg, name), "w") as f:
            f.write(text)

    def entry(self, body):
        return f'"controller_config"\n{{\n\t"{APPID}"\n\t{{\n\t\t{body}\n\t}}\n}}\n'

    def test_saved_layout_is_checked(self):
        f = check_layout(self.root, APPID)
        self.assertEqual([x.id for x in f], ["controller_layout"])
        self.assertIn("A sends RB", f[0].evidence)
        self.assertEqual(f[0].fixes[0].action, "open_controller_settings")

    def test_deck_template_choice_wins_over_generic_autosave(self):
        # What Steam wrote after switching Mirage to a template on the Deck itself
        self.write("configset_FYZZ0000.vdf", self.entry('"template"\t\t"controller_neptune_gamepad+mouse.vdf"'))
        self.assertEqual(check_layout(self.root, APPID), [])

    def test_dualsense_choice_is_ignored(self):
        self.write("configset_DS5000.vdf", self.entry('"template"\t\t"controller_ps5_gamepad_joystick.vdf"'))
        self.assertEqual([x.id for x in check_layout(self.root, APPID)], ["controller_layout"])

    def test_game_without_a_saved_layout(self):
        self.assertEqual(check_layout(self.root, 12345), [])


if __name__ == "__main__":
    unittest.main()
