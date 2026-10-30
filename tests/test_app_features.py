import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app_features import (
    MAX_CLIPBOARD_CACHE_FILES,
    MAX_GEMINI_IMAGE_DIMENSION,
    MAX_IMAGE_REQUEST_SIZE_BYTES,
    MAX_IMAGE_SIZE_BYTES,
    STARTUP_VALUE_NAME,
    THEME_COLOR_MAPS,
    THEME_PALETTES,
    build_startup_command,
    build_user_content,
    discover_installed_apps,
    describe_gemini_error,
    load_preferences,
    load_shortcuts,
    save_clipboard_image,
    save_preferences,
    save_shortcuts,
    scheduled_theme,
    set_windows_startup_enabled,
    speech_language,
    shortcut_targets_to_open,
    translate_text,
    validate_image,
    is_windows_startup_enabled,
)


class ImageAttachmentTests(unittest.TestCase):
    def test_clipboard_image_cache_is_bounded(self):
        class FakeImage:
            size = (640, 480)

            def save(self, path, format):
                self.assert_format = format
                Path(path).write_bytes(b"png image")

        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = Path(temporary)
            for _ in range(MAX_CLIPBOARD_CACHE_FILES + 2):
                save_clipboard_image(FakeImage(), cache_dir)

            self.assertEqual(len(list(cache_dir.glob("clipboard-*.png"))), MAX_CLIPBOARD_CACHE_FILES)

    def test_clipboard_image_cache_rejects_excessive_dimensions(self):
        class HugeImage:
            size = (20_000, 20_000)

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "dimensions are too large"):
                save_clipboard_image(HugeImage(), Path(temporary))
            self.assertFalse(list(Path(temporary).glob("clipboard-*.png")))

    def test_clipboard_image_cache_keeps_selected_files_until_deselected(self):
        class FakeImage:
            size = (640, 480)

            def save(self, path, format):
                Path(path).write_bytes(b"png image")

        with tempfile.TemporaryDirectory() as temporary:
            cache_dir = Path(temporary)
            selected = {
                save_clipboard_image(FakeImage(), cache_dir)
                for _ in range(MAX_CLIPBOARD_CACHE_FILES - 1)
            }
            latest = save_clipboard_image(
                FakeImage(),
                cache_dir,
                preserve_paths=selected,
            )

            self.assertTrue(all(path.is_file() for path in selected))
            self.assertTrue(latest.is_file())
            self.assertEqual(len(list(cache_dir.glob("clipboard-*.png"))), MAX_CLIPBOARD_CACHE_FILES)
            with self.assertRaisesRegex(ValueError, "cannot preserve"):
                save_clipboard_image(
                    FakeImage(),
                    cache_dir,
                    preserve_paths=selected | {latest},
                )

    def test_build_user_content_includes_text_and_image_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "screen.png"
            Image.new("RGB", (64, 48), "white").save(image, format="PNG")
            sdk_types = SimpleNamespace(
                Part=SimpleNamespace(
                    from_text=lambda **kwargs: ("text", kwargs["text"]),
                    from_bytes=lambda **kwargs: (
                        "image",
                        kwargs["data"],
                        kwargs["mime_type"],
                    ),
                ),
                Content=lambda **kwargs: kwargs,
            )

            content = build_user_content("What is shown?", [image], sdk_types)

            self.assertEqual(content["role"], "user")
            self.assertEqual(content["parts"][0], ("text", "What is shown?"))
            self.assertEqual(content["parts"][1][0], "image")
            self.assertEqual(content["parts"][1][2], "image/jpeg")
            with Image.open(BytesIO(content["parts"][1][1])) as optimized:
                self.assertEqual(optimized.size, (64, 48))

    def test_build_user_content_resizes_and_compresses_large_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "large.png"
            source = Image.effect_noise((1800, 1200), 100).convert("RGB")
            source.save(image, format="PNG")
            original_size = image.stat().st_size
            sdk_types = SimpleNamespace(
                Part=SimpleNamespace(
                    from_text=lambda **kwargs: ("text", kwargs["text"]),
                    from_bytes=lambda **kwargs: (
                        "image",
                        kwargs["data"],
                        kwargs["mime_type"],
                    ),
                ),
                Content=lambda **kwargs: kwargs,
            )

            content = build_user_content("What is shown?", [image], sdk_types)
            optimized_bytes = content["parts"][1][1]

            self.assertLess(len(optimized_bytes), original_size)
            self.assertEqual(content["parts"][1][2], "image/jpeg")
            with Image.open(BytesIO(optimized_bytes)) as optimized:
                self.assertLessEqual(max(optimized.size), MAX_GEMINI_IMAGE_DIMENSION)
            with Image.open(image) as original:
                self.assertEqual(original.size, (1800, 1200))

    def test_rejects_unsupported_and_oversized_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            unsupported = Path(temporary) / "photo.bmp"
            unsupported.write_bytes(b"image")
            with self.assertRaises(ValueError):
                validate_image(unsupported)

            oversized = Path(temporary) / "large.png"
            oversized.write_bytes(b"x" * (MAX_IMAGE_SIZE_BYTES + 1))
            with self.assertRaises(ValueError):
                validate_image(oversized)

    def test_rejects_images_exceeding_total_request_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            images = []
            for index in range(3):
                image = Path(temporary) / f"{index}.heic"
                image.write_bytes(b"x" * (7 * 1024 * 1024))
                images.append(image)
            sdk_types = SimpleNamespace(
                Part=SimpleNamespace(
                    from_text=lambda **kwargs: ("text", kwargs["text"]),
                    from_bytes=lambda **kwargs: kwargs,
                ),
                Content=lambda **kwargs: kwargs,
            )

            self.assertGreater(
                sum(image.stat().st_size for image in images),
                MAX_IMAGE_REQUEST_SIZE_BYTES,
            )
            with self.assertRaisesRegex(ValueError, "20 MB"):
                build_user_content("Analyze these", images, sdk_types)


class PreferenceAndLocalizationTests(unittest.TestCase):
    def test_preferences_round_trip_and_default_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preferences.json"
            self.assertEqual(
                load_preferences(path),
                {"language": "English", "theme": "Auto", "voice_output": False},
            )
            preferences = {
                "language": "Français",
                "theme": "Light",
                "voice_output": True,
            }

            save_preferences(preferences, path)

            self.assertEqual(load_preferences(path), preferences)

    def test_preferences_reject_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preferences.json"
            path.write_text(
                json.dumps({"language": "Klingon", "theme": "Auto", "voice_output": False}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported language"):
                load_preferences(path)

    def test_auto_theme_schedule_and_boundaries(self):
        self.assertEqual(scheduled_theme(6), "dark")
        self.assertEqual(scheduled_theme(7), "light")
        self.assertEqual(scheduled_theme(18), "light")
        self.assertEqual(scheduled_theme(19), "dark")
        with self.assertRaises(ValueError):
            scheduled_theme(24)

    def test_day_and_night_palettes_keep_warm_brown_chat_surfaces(self):
        self.assertEqual(THEME_PALETTES["dark"]["app_bg"], "#0a0908")
        self.assertEqual(THEME_PALETTES["light"]["app_bg"], "#fbf8f4")
        self.assertEqual(
            THEME_COLOR_MAPS["light"]["#100f0e"],
            THEME_PALETTES["light"]["panel_bg"],
        )
        self.assertEqual(
            THEME_COLOR_MAPS["light"]["#1a1816"],
            THEME_PALETTES["light"]["assistant_bubble"],
        )
        self.assertEqual(
            THEME_COLOR_MAPS["light"]["#36271e"],
            THEME_PALETTES["light"]["user_bubble"],
        )

    def test_language_translation_and_speech_locale(self):
        self.assertEqual(translate_text("Send", "Français"), "Envoyer")
        self.assertEqual(translate_text("⚙   Settings", "Français"), "⚙   Paramètres")
        self.assertEqual(speech_language("العربية"), "ar-TN")
        self.assertEqual(translate_text("Settings", "العربية"), "الإعدادات")
        self.assertEqual(
            translate_text("●  Gemini Neural Ready", "Français"),
            "●  Gemini prêt",
        )
        self.assertEqual(
            translate_text("2 apps selected", "العربية"),
            "تم اختيار 2 تطبيقات",
        )
        self.assertEqual(
            translate_text("2 image(s): capture.png", "Français"),
            "2 image(s) : capture.png",
        )
        with self.assertRaises(ValueError):
            speech_language("Klingon")

    def test_total_limit_accounts_for_base64_encoding_overhead(self):
        with tempfile.TemporaryDirectory() as temporary:
            images = []
            for index in range(2):
                image = Path(temporary) / f"{index}.heic"
                image.write_bytes(b"x" * (8 * 1024 * 1024))
                images.append(image)
            sdk_types = SimpleNamespace(
                Part=SimpleNamespace(
                    from_text=lambda **kwargs: ("text", kwargs["text"]),
                    from_bytes=lambda **kwargs: kwargs,
                ),
                Content=lambda **kwargs: kwargs,
            )

            self.assertLessEqual(
                sum(image.stat().st_size for image in images),
                MAX_IMAGE_REQUEST_SIZE_BYTES,
            )
            with self.assertRaisesRegex(ValueError, "20 MB"):
                build_user_content("Analyze these", images, sdk_types)


class ShortcutPersistenceTests(unittest.TestCase):
    def test_saves_and_loads_custom_shortcuts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings" / "shortcuts.json"
            shortcuts = [
                {
                    "name": "Coding time",
                    "targets": ["https://google.com", "code"],
                    "max_open": 2,
                }
            ]

            save_shortcuts(shortcuts, path)

            self.assertEqual(load_shortcuts(path), shortcuts)

    def test_old_shortcut_settings_default_to_opening_all_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shortcuts.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Coding time",
                            "targets": ["https://google.com", "code"],
                        }
                    ]
                )
            )

            self.assertEqual(load_shortcuts(path)[0]["max_open"], 2)

    def test_discovery_lists_and_deduplicates_start_menu_apps(self):
        with tempfile.TemporaryDirectory() as temporary:
            user_root = Path(temporary) / "user"
            machine_root = Path(temporary) / "machine"
            user_programs = user_root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            machine_programs = machine_root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            (user_programs / "Utilities").mkdir(parents=True)
            machine_programs.mkdir(parents=True)
            user_link = user_programs / "Utilities" / "Visual Studio Code.lnk"
            duplicate_link = machine_programs / "Visual Studio Code.lnk"
            browser_link = machine_programs / "Chrome.lnk"
            for shortcut in (user_link, duplicate_link, browser_link):
                shortcut.touch()

            apps = discover_installed_apps(str(user_root), str(machine_root))

            self.assertEqual(
                [app["name"] for app in apps],
                ["Chrome", "Visual Studio Code"],
            )
            self.assertEqual(apps[1]["target"], f"startmenu:{user_link.resolve()}")

    def test_shortcut_rejects_invalid_max_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shortcuts.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Invalid",
                            "targets": ["code"],
                            "max_open": 0,
                        }
                    ]
                )
            )

            with self.assertRaisesRegex(ValueError, "maximum app count"):
                load_shortcuts(path)

    def test_shortcut_rejects_open_count_larger_than_target_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shortcuts.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Invalid",
                            "targets": ["code"],
                            "max_open": 2,
                        }
                    ]
                )
            )

            with self.assertRaisesRegex(ValueError, "maximum app count"):
                load_shortcuts(path)

    def test_shortcut_launch_count_selects_first_requested_apps(self):
        targets = ["code", "chrome", "https://google.com"]
        self.assertEqual(shortcut_targets_to_open(targets, 2), targets[:2])
        with self.assertRaises(ValueError):
            shortcut_targets_to_open(targets, 4)

    def test_reports_invalid_shortcut_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shortcuts.json"
            path.write_text(json.dumps([{"name": "Missing targets"}]))

            with self.assertRaisesRegex(ValueError, "invalid"):
                load_shortcuts(path)

    def test_startup_command_quotes_paths_and_requests_startup_greeting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "Python with spaces" / "python.exe"
            executable.parent.mkdir()
            executable.touch()
            windowless = executable.with_name("pythonw.exe")
            windowless.touch()
            script = root / "AI Tool Pro Max" / "app.py"

            command = build_startup_command(script, executable)

            self.assertIn(f'"{windowless}"', command)
            self.assertIn(f'"{script}"', command)
            self.assertTrue(command.endswith("--startup"))

    def test_windows_startup_setting_can_be_enabled_and_disabled(self):
        registry_values = {}

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        def query_value(_key, name):
            if name not in registry_values:
                raise FileNotFoundError(name)
            return registry_values[name], 1

        def set_value(_key, name, _reserved, _kind, value):
            registry_values[name] = value

        def delete_value(_key, name):
            if name not in registry_values:
                raise FileNotFoundError(name)
            del registry_values[name]

        fake_winreg = SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            REG_SZ=1,
            OpenKey=lambda *_args: FakeKey(),
            CreateKey=lambda *_args: FakeKey(),
            QueryValueEx=query_value,
            SetValueEx=set_value,
            DeleteValue=delete_value,
        )
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "app.py"
            executable = Path(temporary) / "python.exe"
            with patch.object(sys, "platform", "win32"), patch.dict(
                sys.modules, {"winreg": fake_winreg}
            ):
                set_windows_startup_enabled(True, script, executable)
                self.assertTrue(is_windows_startup_enabled())
                self.assertIn("--startup", registry_values[STARTUP_VALUE_NAME])

                set_windows_startup_enabled(False, script, executable)
                self.assertFalse(is_windows_startup_enabled())


class GeminiErrorMessageTests(unittest.TestCase):
    def test_api_error_messages_never_echo_provider_details_or_keys(self):
        error = RuntimeError("request failed with secret-key-value")

        message = describe_gemini_error(error)

        self.assertNotIn("secret-key-value", message)
        self.assertIn("RuntimeError", message)

    def test_api_error_categories_are_actionable(self):
        unauthorized = type("ApiError", (), {"status_code": 401})()
        quota = SimpleNamespace(status_code=429)
        network = ConnectionError("network unavailable")

        self.assertIn("rejected the API key", describe_gemini_error(unauthorized))
        self.assertIn("quota is exhausted", describe_gemini_error(quota))
        self.assertIn("internet connection", describe_gemini_error(network))
        self.assertIn(
            "Impossible de joindre Gemini",
            describe_gemini_error(network, "Français"),
        )


if __name__ == "__main__":
    unittest.main()
