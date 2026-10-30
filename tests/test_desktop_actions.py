from pathlib import Path
import tempfile
import unittest

from desktop_actions import (
    DesktopActionError,
    clean_desktop,
    launch_program,
    launch_target,
    organize_preview,
    validate_shortcut_target,
)
from unittest.mock import patch


class OrganizeDesktopTests(unittest.TestCase):
    def test_preview_categorizes_files_and_skips_directories_and_hidden_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary)
            (desktop / "photo.JPG").write_text("image")
            (desktop / "notes.txt").write_text("document")
            (desktop / "mystery.xyz").write_text("other")
            (desktop / ".hidden.txt").write_text("hidden")
            (desktop / "already-a-folder").mkdir()

            moves = organize_preview(desktop)

            self.assertEqual(
                [(move.source.name, move.destination.parent.name) for move in moves],
                [
                    ("mystery.xyz", "Other"),
                    ("notes.txt", "Documents"),
                    ("photo.JPG", "Images"),
                ],
            )
            self.assertFalse((desktop / "Other").exists())

    def test_preview_avoids_overwriting_existing_destinations(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary)
            (desktop / "report.pdf").write_text("new")
            folder = desktop / "Documents"
            folder.mkdir()
            (folder / "report.pdf").write_text("existing")

            moves = organize_preview(desktop)

            self.assertEqual(moves[0].destination.name, "report (1).pdf")

    def test_clean_moves_files_without_deleting_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary)
            source = desktop / "image.png"
            source.write_text("image")

            moved = clean_desktop(organize_preview(desktop))

            self.assertEqual(len(moved), 1)
            self.assertFalse(source.exists())
            self.assertEqual((desktop / "Images" / "image.png").read_text(), "image")

    def test_invalid_program_is_rejected(self):
        with self.assertRaises(DesktopActionError):
            launch_program("unsupported")

    def test_missing_desktop_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing"
            with self.assertRaises(DesktopActionError):
                organize_preview(missing)

    def test_shortcut_target_accepts_apps_and_http_urls(self):
        validate_shortcut_target("code")
        validate_shortcut_target("https://www.google.com")

    def test_shortcut_target_rejects_unsafe_urls_and_unknown_apps(self):
        with self.assertRaises(DesktopActionError):
            validate_shortcut_target("file:///C:/Users/test/file.txt")
        with self.assertRaises(DesktopActionError):
            validate_shortcut_target("unknown application")

    def test_start_menu_shortcut_target_is_validated_and_opened(self):
        with tempfile.TemporaryDirectory() as temporary:
            shortcut = Path(temporary) / "Installed app.lnk"
            shortcut.touch()
            target = f"startmenu:{shortcut}"

            with patch("desktop_actions.os.startfile", create=True) as startfile:
                validate_shortcut_target(target)
                launch_target(target)

            startfile.assert_called_once_with(str(shortcut))

    @patch("desktop_actions.webbrowser.open", return_value=True)
    def test_launch_target_opens_website(self, open_browser):
        launch_target("https://www.google.com")
        open_browser.assert_called_once_with("https://www.google.com", new=2)


if __name__ == "__main__":
    unittest.main()
