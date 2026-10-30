from __future__ import annotations

import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any
from fastapi import FastAPI

app = FastAPI()  # Assurez-vous que c'est bien nommé "app" et au niveau racine
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageGrab, ImageTk

from backend import (
    BackendRequestError,
    BackendStartupError,
    LocalBackend,
    MODEL_NAME,
)
from app_features import (
    MAX_IMAGE_ATTACHMENTS,
    MAX_SHORTCUT_TARGETS,
    PREFERENCES_FILE,
    SHORTCUTS_FILE,
    THEME_COLOR_MAPS,
    THEME_PALETTES,
    discover_installed_apps,
    describe_gemini_error,
    is_windows_startup_enabled,
    load_preferences,
    load_shortcuts,
    save_clipboard_image,
    save_preferences,
    save_shortcuts,
    scheduled_theme,
    speech_language,
    shortcut_targets_to_open,
    set_windows_startup_enabled,
    translate_text,
    validate_image,
)
from desktop_actions import (
    DesktopActionError,
    clean_desktop,
    get_desktop_path,
    launch_program,
    launch_target,
    organize_preview,
    take_screenshot,
    validate_shortcut_target,
)

TTS_LOCK = threading.Lock()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

FONT_FAMILY = "Segoe UI"


def _font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def _create_app_logo(size: int = 96) -> Image.Image:
    image = Image.new("RGBA", (size, size), "#211812")
    draw = ImageDraw.Draw(image)
    points = [
        (48, 19),
        (54, 40),
        (75, 46),
        (54, 52),
        (48, 73),
        (42, 52),
        (21, 46),
        (42, 40),
    ]
    scale = size / 96
    points = [(round(x * scale), round(y * scale)) for x, y in points]
    draw.rounded_rectangle(
        (2, 2, size - 3, size - 3),
        radius=round(size * 0.29),
        fill="#211812",
    )
    draw.polygon(points, fill="#e5a66d")
    draw.ellipse(
        (round(25 * scale), round(64 * scale), round(33 * scale), round(72 * scale)),
        fill="#fff2e5",
    )
    return image


class AIToolProMax(ctk.CTk):
    def __init__(self, startup_mode: bool = False) -> None:
        super().__init__()
        self.title("AI Help You")
        self.geometry("1180x800")
        self.minsize(860, 600)
        self._logo_pil_image = _create_app_logo()
        self._logo_image = ctk.CTkImage(
            light_image=self._logo_pil_image,
            dark_image=self._logo_pil_image,
            size=(38, 38),
        )
        self._window_logo_image = ImageTk.PhotoImage(self._logo_pil_image)
        self.iconphoto(True, self._window_logo_image)
        self.configure(fg_color="#0a0a0a")
        try:
            self._preferences = load_preferences()
        except ValueError as exc:
            self._preferences = {
                "language": "English",
                "theme": "Auto",
                "voice_output": False,
            }
            self.after(
                300,
                lambda error=exc: messagebox.showerror(
                    "Could not load preferences", str(error), parent=self
                ),
            )
        self._language = self._preferences["language"]
        self._theme_preference = self._preferences["theme"]
        self._active_theme = "dark"
        self._status_source = "Ready when you are."
        self._connection_source = "●  Gemini Neural Disconnected"
        self._original_widget_texts: dict[Any, str] = {}
        self._original_widget_colors: dict[Any, dict[str, Any]] = {}
        self._original_window_titles: dict[Any, str] = {self: "AI Help You"}
        self._theme_after_id: str | None = None
        self._status_after_id: str | None = None
        self._fade_after_id: str | None = None
        self._window_fade_supported = True
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            self._window_fade_supported = False

        self._history: list[dict[str, Any]] = []
        self._selected_images: list[Path] = []
        self._message_image_refs: list[ctk.CTkImage] = []
        self._preview_window: ctk.CTkToplevel | None = None
        self._settings_window: ctk.CTkToplevel | None = None
        self._settings_language_menu: ctk.CTkOptionMenu | None = None
        self._settings_theme_menu: ctk.CTkOptionMenu | None = None
        self._shortcut_editor: ctk.CTkToplevel | None = None
        self._installed_app_picker: ctk.CTkToplevel | None = None
        self._voice_output = tk.BooleanVar(value=self._preferences["voice_output"])
        self._busy = False
        self._api_test_running = False
        self._credit_balance = 500
        self._credit_reset_at: datetime | None = None
        self._credits_after_id: str | None = None
        self._typing_indicator: ctk.CTkFrame | None = None
        self._typing_after_id: str | None = None
        self._sidebar_visible = True
        self._pulse_on = True
        self._gemini_connected = False
        self._backend: LocalBackend | None = None
        self._backend_error: str | None = None
        self._startup_mode = startup_mode
        try:
            self._shortcuts = load_shortcuts()
        except ValueError as exc:
            self._shortcuts = []
            self.after(
                300,
                lambda error=exc: messagebox.showerror(
                    "Could not load shortcuts", str(error), parent=self
                ),
            )

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main_panel()
        self._register_localizable_widgets(self)
        self._apply_language()
        self._apply_theme()
        self._schedule_theme_refresh()
        try:
            self._backend = LocalBackend()
            self._refresh_credit_balance()
        except BackendStartupError as exc:
            self._backend_error = str(exc)
            self.after(
                500,
                lambda error=exc: messagebox.showerror(
                    "Local backend unavailable", str(error), parent=self
                ),
            )
        if self._startup_mode:
            self._set_status("AI Help You opened with Windows. Ready to help.")
        self._update_connection_status()
        self._schedule_credit_refresh()
        self._animate_status()
        self._fade_after_id = self.after(30, lambda: self._animate_window_fade(0))
        self.protocol("WM_DELETE_WINDOW", self._close_application)

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(
            self, width=250, corner_radius=0, fg_color="#120f0e"
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(8, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=20, pady=(26, 8), sticky="w")
        ctk.CTkLabel(brand, text="", image=self._logo_image).pack(side="left", padx=(0, 9))
        ctk.CTkLabel(
            brand,
            text="AI HELP YOU",
            justify="left",
            font=_font(size=17, weight="bold"),
            text_color="#ffffff",
        ).pack(side="left")
        ctk.CTkLabel(
            self.sidebar,
            text="DESKTOP INTELLIGENCE HUB",
            font=_font(size=10, weight="bold"),
            text_color="#d48c51",
        ).grid(row=1, column=0, padx=23, pady=(0, 18), sticky="w")

        ctk.CTkLabel(
            self.sidebar,
            text="QUICK ACTIONS",
            font=_font(size=11, weight="bold"),
            text_color="#958a83",
        ).grid(row=2, column=0, padx=20, pady=(2, 6), sticky="w")

        actions = [
            ("⌘   Clean desktop", lambda: self._run_sidebar_action(self._clean_desktop)),
            (
                "◉   Open browser",
                lambda: self._run_sidebar_action(lambda: self._launch("browser")),
            ),
            (
                "▤   Open text editor",
                lambda: self._run_sidebar_action(lambda: self._launch("notepad")),
            ),
            (
                "⚙   Open calculator",
                lambda: self._run_sidebar_action(lambda: self._launch("calculator")),
            ),
        ]
        for row, (label, command) in enumerate(actions, start=3):
            ctk.CTkButton(
                self.sidebar,
                text=label,
                command=command,
                anchor="w",
                height=38,
                corner_radius=10,
                fg_color="#1f1815",
                hover_color="#2b211b",
                text_color="#e8e2de",
                border_width=1,
                border_color="#2c2521",
            ).grid(row=row, column=0, padx=14, pady=2, sticky="ew")

        ctk.CTkLabel(
            self.sidebar,
            text="MY SHORTCUTS",
            font=_font(size=11, weight="bold"),
            text_color="#958a83",
        ).grid(row=7, column=0, padx=20, pady=(18, 8), sticky="w")
        self.shortcut_buttons = ctk.CTkScrollableFrame(
            self.sidebar,
            height=100,
            fg_color="transparent",
            scrollbar_button_color="#42352d",
            scrollbar_button_hover_color="#d48c51",
        )
        self.shortcut_buttons.grid(row=8, column=0, padx=14, sticky="nsew")
        self._refresh_shortcut_buttons()
        ctk.CTkButton(
            self.sidebar,
            text="+ Create / edit shortcuts",
            command=self._open_shortcut_editor,
            anchor="w",
            height=36,
            corner_radius=10,
            fg_color="#1f1815",
            hover_color="#34261e",
            text_color="#d48c51",
        ).grid(row=9, column=0, padx=14, pady=(6, 2), sticky="ew")
        ctk.CTkButton(
            self.sidebar,
            text="⚙   Settings",
            command=self._open_settings,
            anchor="w",
            height=40,
            corner_radius=10,
            fg_color="#1f1815",
            hover_color="#34261e",
            text_color="#e8e2de",
            border_width=1,
            border_color="#2c2521",
        ).grid(row=10, column=0, padx=14, pady=(8, 4), sticky="ew")
        self.startup_enabled = tk.BooleanVar(value=self._get_startup_enabled())

        ctk.CTkFrame(self.sidebar, height=1, fg_color="#2c2521").grid(
            row=11, column=0, padx=20, pady=(8, 10), sticky="ew"
        )
        ctk.CTkLabel(
            self.sidebar,
            text="Local actions stay on your PC.\nGemini needs an API key.",
            justify="left",
            font=_font(size=11),
            text_color="#958a83",
        ).grid(row=12, column=0, padx=20, pady=(0, 20), sticky="sw")

    def _build_main_panel(self) -> None:
        main = ctk.CTkFrame(self, fg_color="#0a0a0a", corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=24, pady=18)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.grid_columnconfigure(1, weight=1)
        self.sidebar_toggle = ctk.CTkButton(
            header,
            text="☰",
            width=38,
            height=36,
            command=self._toggle_sidebar,
            fg_color="#1f1815",
            hover_color="#34261e",
            text_color="#d48c51",
        )
        self.sidebar_toggle.grid(row=0, column=0, padx=(0, 12))

        ctk.CTkLabel(
            header,
            text="Your personal AI companion",
            font=_font(size=18, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=1, sticky="w")
        self.connection_label = ctk.CTkLabel(
            header,
            text="●  Gemini Neural Disconnected",
            font=_font(size=11, weight="bold"),
            text_color="#a49a94",
        )
        self.connection_label.grid(row=0, column=2, padx=(8, 12), sticky="e")
        self.api_test_button = ctk.CTkButton(
            header,
            text="Test API",
            width=84,
            height=34,
            command=self._test_gemini_api,
            corner_radius=10,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#d48c51",
            border_width=1,
            border_color="#493326",
        )
        self.api_test_button.grid(row=0, column=3, sticky="e")

        self.chat = ctk.CTkScrollableFrame(
            main,
            fg_color="#100f0e",
            corner_radius=18,
            scrollbar_button_color="#42352d",
            scrollbar_button_hover_color="#d48c51",
        )
        self.chat.grid(row=1, column=0, sticky="nsew")
        self.chat.grid_columnconfigure(0, weight=1)
        self._show_welcome()

        self.status_label = ctk.CTkLabel(
            main,
            text="Ready when you are.",
            anchor="w",
            font=_font(size=11),
            text_color="#958a83",
        )
        self.status_label.grid(row=2, column=0, sticky="ew", padx=8, pady=(12, 4))

        input_panel = ctk.CTkFrame(
            main,
            fg_color="#171412",
            corner_radius=18,
            border_width=1,
            border_color="#342a24",
        )
        input_panel.grid(row=3, column=0, sticky="ew")
        input_panel.grid_columnconfigure(0, weight=1)
        self.input_field = ctk.CTkTextbox(
            input_panel,
            height=50,
            wrap="word",
            fg_color="transparent",
            border_width=0,
            text_color="#ffffff",
            font=_font(size=14),
        )
        self.input_field.grid(
            row=0, column=0, columnspan=7, padx=14, pady=(8, 2), sticky="ew"
        )
        self.input_field.bind("<Return>", self._on_enter)
        self.input_field.bind("<Control-v>", self._paste_clipboard_image)
        self.input_field.bind("<Control-V>", self._paste_clipboard_image)

        self.attachment_preview = ctk.CTkLabel(
            input_panel,
            text="",
            width=50,
            height=48,
            corner_radius=8,
            fg_color="#100d0b",
        )
        self.attachment_preview.grid(
            row=1, column=0, padx=(10, 4), pady=(2, 4), sticky="w"
        )
        self.attachment_preview.bind("<Button-1>", self._open_attachment_preview)
        self.attachments_label = ctk.CTkLabel(
            input_panel,
            text="No images attached",
            anchor="w",
            text_color="#958a83",
            font=_font(size=10),
        )
        self.attachments_label.grid(
            row=1, column=1, padx=(4, 8), pady=(2, 4), sticky="ew"
        )
        self.attach_button = ctk.CTkButton(
            input_panel,
            text="＋ Image",
            width=78,
            height=34,
            command=self._choose_images,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#e8e2de",
        )
        self.attach_button.grid(row=1, column=2, padx=3, pady=(2, 4))
        self.capture_attach_button = ctk.CTkButton(
            input_panel,
            text="▧ Screen",
            width=82,
            height=34,
            command=lambda: self._run_sidebar_action(self._capture_and_attach),
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#d48c51",
        )
        self.capture_attach_button.grid(row=1, column=3, padx=3, pady=(2, 4))
        self.clear_attachments_button = ctk.CTkButton(
            input_panel,
            text="Clear",
            width=44,
            height=34,
            command=self._clear_image_attachments,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#e8e2de",
            border_width=1,
            border_color="#42352d",
            state="disabled",
        )
        self.clear_attachments_button.grid(row=1, column=4, padx=2, pady=(2, 4))
        self.voice_button = ctk.CTkButton(
            input_panel,
            text="🎙",
            width=40,
            height=34,
            command=self._listen,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#d48c51",
        )
        self.voice_button.grid(row=1, column=5, padx=3, pady=(2, 4))
        self.send_button = ctk.CTkButton(
            input_panel,
            text="Send",
            width=74,
            height=34,
            command=self._send_message,
            corner_radius=12,
            fg_color="#d48c51",
            hover_color="#b97842",
            text_color="#100d0b",
            font=_font(weight="bold"),
        )
        self.send_button.grid(row=1, column=6, padx=(3, 10), pady=(2, 4))
        input_panel.grid_columnconfigure(0, weight=0)
        input_panel.grid_columnconfigure(1, weight=1)
        input_panel.grid_columnconfigure(2, weight=0)
        input_panel.grid_columnconfigure(3, weight=0)
        input_panel.grid_columnconfigure(4, weight=0)
        input_panel.grid_columnconfigure(5, weight=0)
        input_panel.grid_columnconfigure(6, weight=0)

        controls = ctk.CTkFrame(main, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        ctk.CTkSwitch(
            controls,
            text="Voice output",
            variable=self._voice_output,
            command=self._change_voice_output,
            onvalue=True,
            offvalue=False,
            progress_color="#d48c51",
            button_color="#ffffff",
            button_hover_color="#e5b07f",
            text_color="#e8e2de",
            font=_font(size=11),
        ).pack(side="left")
        self.credits_label = ctk.CTkLabel(
            controls,
            text="Credits: 500/500",
            text_color="#d48c51",
            font=_font(size=11, weight="bold"),
        )
        self.credits_label.pack(side="left", padx=(18, 8))
        ctk.CTkLabel(
            controls,
            text="Enter to send · Shift+Enter for a new line",
            text_color="#746b65",
            font=_font(size=10),
        ).pack(side="right")

    def _tr(self, text: str) -> str:
        return translate_text(text, self._language)

    def _open_settings(self) -> None:
        if self._settings_window is not None:
            try:
                if self._settings_window.winfo_exists():
                    self._settings_window.deiconify()
                    self._settings_window.lift()
                    self._settings_window.focus_force()
                    return
            except tk.TclError:
                pass
            self._forget_settings_window(self._settings_window)

        settings = ctk.CTkToplevel(self)
        settings.title("Settings")
        settings.geometry("440x420")
        settings.minsize(400, 380)
        settings.transient(self)
        settings.grid_columnconfigure(0, weight=1)
        self._settings_window = settings
        self._original_window_titles[settings] = "Settings"

        ctk.CTkLabel(
            settings,
            text="Settings",
            font=_font(size=23, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=0, padx=24, pady=(22, 16), sticky="w")
        ctk.CTkLabel(
            settings,
            text="Language",
            font=_font(size=12, weight="bold"),
            text_color="#b9ada5",
        ).grid(row=1, column=0, padx=24, pady=(0, 5), sticky="w")
        self._settings_language_menu = ctk.CTkOptionMenu(
            settings,
            values=["English", "Français", "العربية"],
            command=self._change_language,
            height=38,
            fg_color="#1f1815",
            button_color="#493326",
            button_hover_color="#6e5847",
            text_color="#e8e2de",
        )
        self._settings_language_menu.set(self._language)
        self._settings_language_menu.grid(
            row=2, column=0, padx=24, pady=(0, 14), sticky="ew"
        )
        ctk.CTkLabel(
            settings,
            text="Appearance",
            font=_font(size=12, weight="bold"),
            text_color="#b9ada5",
        ).grid(row=3, column=0, padx=24, pady=(0, 5), sticky="w")
        self._settings_theme_menu = ctk.CTkOptionMenu(
            settings,
            values=["Auto", "Dark", "Light"],
            command=self._change_theme_preference,
            height=38,
            fg_color="#1f1815",
            button_color="#493326",
            button_hover_color="#6e5847",
            text_color="#e8e2de",
        )
        self._settings_theme_menu.set(self._theme_preference)
        self._settings_theme_menu.grid(
            row=4, column=0, padx=24, pady=(0, 16), sticky="new"
        )

        startup_panel = ctk.CTkFrame(
            settings,
            fg_color="#171412",
            corner_radius=12,
            border_width=1,
            border_color="#342a24",
        )
        startup_panel.grid(
            row=5, column=0, padx=24, pady=(0, 20), sticky="ew"
        )
        ctk.CTkSwitch(
            startup_panel,
            text="Start with Windows",
            variable=self.startup_enabled,
            command=self._toggle_windows_startup,
            progress_color="#d48c51",
            button_color="#ffffff",
            button_hover_color="#e5b07f",
            text_color="#e8e2de",
            font=_font(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            startup_panel,
            text="Open AI Help You automatically when you sign in.",
            anchor="w",
            wraplength=350,
            text_color="#958a83",
            font=_font(size=11),
        ).pack(anchor="w", padx=16, pady=(0, 14))

        settings.protocol("WM_DELETE_WINDOW", self._close_settings)
        settings.bind(
            "<Destroy>",
            lambda event, window=settings: self._on_settings_destroy(event, window),
            add="+",
        )
        self._register_localizable_widgets(settings)
        self._apply_language()
        self._apply_theme()

    def _close_settings(self) -> None:
        settings = self._settings_window
        if settings is None:
            return
        self._forget_settings_window(settings)
        try:
            if settings.winfo_exists():
                settings.destroy()
        except tk.TclError:
            pass

    def _on_settings_destroy(self, event: tk.Event, settings: Any) -> None:
        if event.widget is settings:
            self._forget_settings_window(settings)

    def _forget_settings_window(self, settings: Any) -> None:
        self._original_window_titles.pop(settings, None)

        def belongs_to_settings(widget: Any) -> bool:
            try:
                return widget.winfo_toplevel() is settings
            except tk.TclError:
                return True

        self._original_widget_texts = {
            widget: text
            for widget, text in self._original_widget_texts.items()
            if not belongs_to_settings(widget)
        }
        self._original_widget_colors = {
            widget: colors
            for widget, colors in self._original_widget_colors.items()
            if not belongs_to_settings(widget)
        }
        if self._settings_window is settings:
            self._settings_window = None
            self._settings_language_menu = None
            self._settings_theme_menu = None

    def _register_localizable_widgets(self, parent: Any) -> None:
        for widget in parent.winfo_children():
            if isinstance(
                widget,
                (ctk.CTkLabel, ctk.CTkButton, ctk.CTkSwitch, ctk.CTkCheckBox),
            ):
                text = widget.cget("text")
                if isinstance(text, str):
                    self._original_widget_texts.setdefault(widget, text)
            self._register_localizable_widgets(widget)

    def _apply_language(self) -> None:
        for widget, original_text in list(self._original_widget_texts.items()):
            try:
                if widget.winfo_exists():
                    widget.configure(text=self._tr(original_text))
                    if self._language == "العربية" and isinstance(widget, ctk.CTkLabel):
                        widget.configure(justify="right")
            except tk.TclError:
                self._original_widget_texts.pop(widget, None)
        for window, original_title in list(self._original_window_titles.items()):
            try:
                if window.winfo_exists():
                    window.title(self._tr(original_title))
            except tk.TclError:
                self._original_window_titles.pop(window, None)
        if self._settings_language_menu is not None:
            self._settings_language_menu.set(self._language)
        if self._settings_theme_menu is not None:
            themes = ["Auto", "Dark", "Light"]
            self._settings_theme_menu.configure(
                values=[self._tr(theme) for theme in themes]
            )
            self._settings_theme_menu.set(self._tr(self._theme_preference))
        if hasattr(self, "status_label"):
            self.status_label.configure(text=self._tr(self._status_source))
        if hasattr(self, "connection_label"):
            self._set_connection_status(
                self._connection_source,
                self.connection_label.cget("text_color"),
            )
        self._update_credit_display()

    def _save_current_preferences(self) -> None:
        save_preferences(
            {
                "language": self._language,
                "theme": self._theme_preference,
                "voice_output": self._voice_output.get(),
            },
            PREFERENCES_FILE,
        )

    def _change_language(self, language: str) -> None:
        previous_language = self._language
        self._language = language
        try:
            self._save_current_preferences()
        except ValueError as exc:
            self._language = previous_language
            if self._settings_language_menu is not None:
                self._settings_language_menu.set(previous_language)
            messagebox.showerror("Could not save preferences", str(exc), parent=self)
            return
        self._apply_language()

    def _change_theme_preference(self, theme: str) -> None:
        options = ("Auto", "Dark", "Light")
        theme = next((option for option in options if self._tr(option) == theme), theme)
        if theme not in options:
            messagebox.showerror(
                "Unsupported appearance",
                f"'{theme}' is not a supported appearance setting.",
                parent=self,
            )
            return
        previous_theme = self._theme_preference
        self._theme_preference = theme
        try:
            self._save_current_preferences()
        except ValueError as exc:
            self._theme_preference = previous_theme
            if self._settings_theme_menu is not None:
                self._settings_theme_menu.set(self._tr(previous_theme))
            messagebox.showerror("Could not save preferences", str(exc), parent=self)
            return
        if hasattr(self, "status_label"):
            self._apply_theme()
            self.update_idletasks()
            settings = self._settings_window
            if settings is not None and settings.winfo_exists():
                settings.lift()
                settings.focus_force()
        self._schedule_theme_refresh()

    def _change_voice_output(self) -> None:
        try:
            self._save_current_preferences()
        except ValueError as exc:
            self._voice_output.set(not self._voice_output.get())
            messagebox.showerror("Could not save preferences", str(exc), parent=self)

    def _map_theme_color(self, color: Any, theme: str) -> Any:
        if isinstance(color, str):
            return THEME_COLOR_MAPS[theme].get(color.lower(), color)
        if isinstance(color, (tuple, list)):
            mapped = [self._map_theme_color(item, theme) for item in color]
            return tuple(mapped) if isinstance(color, tuple) else mapped
        return color

    def _apply_theme(self) -> None:
        theme = (
            scheduled_theme(datetime.now().hour)
            if self._theme_preference == "Auto"
            else self._theme_preference.casefold()
        )
        self._active_theme = theme

        def theme_options(widget: Any) -> tuple[str, ...]:
            if isinstance(widget, ctk.CTkScrollableFrame):
                return (
                    "fg_color",
                    "bg_color",
                    "border_color",
                    "scrollbar_button_color",
                    "scrollbar_button_hover_color",
                )
            if isinstance(widget, ctk.CTkOptionMenu):
                return (
                    "fg_color",
                    "bg_color",
                    "text_color",
                    "button_color",
                    "button_hover_color",
                    "dropdown_fg_color",
                    "dropdown_hover_color",
                    "dropdown_text_color",
                )
            if isinstance(widget, ctk.CTkSwitch):
                return (
                    "fg_color",
                    "bg_color",
                    "text_color",
                    "border_color",
                    "button_color",
                    "button_hover_color",
                    "progress_color",
                )
            if isinstance(widget, ctk.CTkCheckBox):
                return ("fg_color", "bg_color", "text_color", "border_color", "hover_color")
            if isinstance(widget, ctk.CTkButton):
                return ("fg_color", "bg_color", "text_color", "border_color", "hover_color")
            if isinstance(widget, ctk.CTkLabel):
                return ("fg_color", "bg_color", "text_color")
            if isinstance(widget, ctk.CTkTextbox):
                return (
                    "fg_color",
                    "bg_color",
                    "text_color",
                    "border_color",
                    "scrollbar_button_color",
                    "scrollbar_button_hover_color",
                )
            if isinstance(widget, ctk.CTkEntry):
                return (
                    "fg_color",
                    "bg_color",
                    "text_color",
                    "border_color",
                    "placeholder_text_color",
                )
            if isinstance(widget, ctk.CTkFrame):
                return ("fg_color", "bg_color", "border_color")
            return ()

        def remember_original_colors(parent: Any) -> None:
            for widget in parent.winfo_children():
                original = self._original_widget_colors.setdefault(widget, {})
                for option in theme_options(widget):
                    if option not in original:
                        original[option] = widget.cget(option)
                remember_original_colors(widget)

        remember_original_colors(self)
        for window in list(self._original_window_titles):
            if window is not self:
                try:
                    if window.winfo_exists():
                        remember_original_colors(window)
                except tk.TclError:
                    self._original_window_titles.pop(window, None)

        ctk.set_appearance_mode(theme)

        def recolor(parent: Any) -> None:
            for widget in parent.winfo_children():
                original = self._original_widget_colors.setdefault(widget, {})
                changes = {
                    option: self._map_theme_color(original[option], theme)
                    for option in theme_options(widget)
                }
                if changes:
                    widget.configure(**changes)
                recolor(widget)

        recolor(self)
        palette = THEME_PALETTES[theme]
        self.configure(fg_color=palette["app_bg"])
        for window in list(self._original_window_titles):
            if window is self:
                continue
            try:
                if window.winfo_exists():
                    window.configure(fg_color=palette["panel_bg"])
                    recolor(window)
            except tk.TclError:
                self._original_window_titles.pop(window, None)

    def _schedule_theme_refresh(self) -> None:
        if self._theme_after_id is not None:
            self.after_cancel(self._theme_after_id)
            self._theme_after_id = None
        if self._theme_preference == "Auto":
            self._apply_theme()
            self._theme_after_id = self.after(60_000, self._schedule_theme_refresh)

    def _close_application(self) -> None:
        for callback_id in (
            self._theme_after_id,
            self._status_after_id,
            self._fade_after_id,
            self._credits_after_id,
        ):
            if callback_id is not None:
                try:
                    self.after_cancel(callback_id)
                except tk.TclError:
                    pass
        self._theme_after_id = None
        self._status_after_id = None
        self._fade_after_id = None
        self._credits_after_id = None
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self.destroy()

    def _refresh_credit_balance(self) -> None:
        if self._backend is None:
            return
        try:
            self._apply_credit_balance(self._backend.credits())
        except BackendRequestError as exc:
            self._set_status(str(exc))

    def _apply_credit_balance(self, balance: dict[str, Any]) -> None:
        try:
            self._credit_balance = max(0, min(500, int(balance["credits"])))
            self._credit_reset_at = datetime.fromisoformat(balance["reset_at"])
        except (KeyError, TypeError, ValueError) as exc:
            self._set_status(f"Could not read the daily credit balance: {exc}")
            return
        self._update_credit_display()

    def _update_credit_display(self) -> None:
        if not hasattr(self, "credits_label"):
            return
        remaining = self._credit_time_remaining()
        locked = self._credit_balance < 5
        if locked:
            self.credits_label.configure(
                text=self._credit_locked_text(remaining),
                text_color="#e07a68",
            )
            self.send_button.configure(state="disabled", text="Locked")
            return
        self.credits_label.configure(
            text=self._credit_available_text(remaining),
            text_color="#d48c51",
        )
        self.send_button.configure(
            state="disabled" if self._busy or self._api_test_running else "normal",
            text="..." if self._busy else "Send",
        )

    def _credit_time_remaining(self) -> str:
        if self._credit_reset_at is None:
            return "00:00:00"
        now = datetime.now().astimezone()
        reset_at = self._credit_reset_at
        if reset_at.tzinfo is None:
            reset_at = reset_at.astimezone()
        seconds = max(0, int((reset_at - now).total_seconds()))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _credit_available_text(self, remaining: str) -> str:
        credits = self._credit_balance
        if self._language == "Français":
            return f"Crédits : {credits}/500 · minuit dans {remaining}"
        if self._language == "العربية":
            return f"رصيدك: {credits}/500 · يتجدّد بعد {remaining}"
        return f"Credits: {credits}/500 · reset in {remaining}"

    def _credit_locked_text(self, remaining: str) -> str:
        if self._language == "Français":
            return f"Bloqué · crédits épuisés · attendez {remaining}"
        if self._language == "العربية":
            return f"مقفول · وفى الرصيد · استنى {remaining}"
        return f"Locked · wait {remaining} for 00:00"

    def _credit_locked_message(self) -> str:
        remaining = self._credit_time_remaining()
        if self._language == "Français":
            return (
                "Bloqué : vos 500 crédits quotidiens sont épuisés. "
                f"Attendez {remaining} jusqu’à 00:00."
            )
        if self._language == "العربية":
            return (
                "مقفول: رصيدك اليومي وفى. استنى "
                f"{remaining} لين 00:00 باش يتجدّد."
            )
        return (
            "Locked: your 500 daily credits are used up. "
            f"Wait {remaining} until 00:00."
        )

    def _schedule_credit_refresh(self) -> None:
        if self._credits_after_id is not None:
            try:
                self.after_cancel(self._credits_after_id)
            except tk.TclError:
                pass
        self._update_credit_display()
        if self._credit_time_remaining() == "00:00:00":
            self._refresh_credit_balance()
        self._credits_after_id = self.after(1000, self._schedule_credit_refresh)

    def _show_welcome(self) -> None:
        greetings = {
            "English": "Hey! I’m here to help with questions, ideas, and everyday tasks. "
            "Attach an image or screenshot to ask about it, or create a shortcut "
            "to open your favorite apps and websites together.",
            "Français": "Bonjour ! Je peux vous aider avec vos questions et vos tâches. "
            "Joignez une image ou une capture d’écran, ou créez un raccourci pour "
            "ouvrir vos applications et sites préférés.",
            "العربية": "أهلًا! أنا هنا لمساعدتك في أسئلتك ومهامك اليومية. أرفق صورة "
            "أو لقطة شاشة لأسأل عنها، أو أنشئ اختصارًا لفتح تطبيقاتك ومواقعك المفضلة.",
        }
        if self._startup_mode:
            startup_greetings = {
                "English": "Hello! What can I help you with today? Ask a question, "
                "share a screenshot, or open a saved shortcut.",
                "Français": "Bonjour ! Comment puis-je vous aider aujourd’hui ? "
                "Posez une question, partagez une capture d’écran ou ouvrez un raccourci.",
                "العربية": "وينك! شنوة تحب نعاونك اليوم؟ تنجم تسألني على أي مشكلة، "
                "تبعثلي تصويرة ولا screenshot، ولا تحلّ اختصاراتك من القائمة.",
            }
            self._add_message(
                "assistant",
                startup_greetings[self._language],
            )
            return
        self._add_message("assistant", greetings[self._language])

    def _toggle_sidebar(self) -> None:
        if self._sidebar_visible:
            self.sidebar.grid_remove()
            self.grid_columnconfigure(0, weight=0, minsize=0)
        else:
            self.sidebar.grid()
            self.grid_columnconfigure(0, weight=0, minsize=250)
        self._sidebar_visible = not self._sidebar_visible

    def _update_connection_status(self) -> None:
        if self._backend_error:
            self._set_connection_status("●  Local backend unavailable", "#e07a68")
            return
        if self._backend is None:
            self._set_connection_status(
                "●  Gemini Neural Disconnected", "#a49a94"
            )
            return
        try:
            health = self._backend.health()
        except BackendRequestError:
            self._set_connection_status("●  Local backend unavailable", "#e07a68")
            return
        if not health.get("gemini_configured"):
            self._set_connection_status("●  Gemini API key not configured", "#e0a168")
            return
        self._set_connection_status("●  Gemini Neural Ready", "#d48c51")

    def _set_connection_status(self, text: str, color: str) -> None:
        self._connection_source = text
        self.connection_label.configure(text=self._tr(text), text_color=color)

    def _animate_status(self) -> None:
        if self._gemini_connected:
            color = "#d48c51" if self._pulse_on else "#926744"
            self.connection_label.configure(text_color=color)
            self._pulse_on = not self._pulse_on
        self._status_after_id = self.after(850, self._animate_status)

    def _animate_window_fade(self, step: int) -> None:
        if not self._window_fade_supported:
            return
        opacity = min(step / 12, 1.0)
        try:
            self.attributes("-alpha", opacity)
        except tk.TclError:
            self._window_fade_supported = False
            return
        if opacity < 1:
            self._fade_after_id = self.after(
                18, lambda: self._animate_window_fade(step + 1)
            )

    def _test_gemini_api(self) -> None:
        if self._busy or self._api_test_running:
            return
        if self._backend is None:
            messagebox.showerror(
                "Local backend unavailable",
                self._backend_error
                or "The local AI backend is unavailable. Restart the app.",
                parent=self,
            )
            return

        self._api_test_running = True
        self.api_test_button.configure(state="disabled", text="Testing…")
        self.send_button.configure(state="disabled")
        self._set_connection_status("●  Testing Gemini connection…", "#d48c51")
        self._set_status("Sending a small test request to Gemini…")
        threading.Thread(target=self._run_gemini_api_test, daemon=True).start()

    def _run_gemini_api_test(self) -> None:
        try:
            if self._backend is None:
                raise BackendRequestError(
                    self._backend_error
                    or "The local AI backend is unavailable. Restart the app."
                )
            self._backend.test_gemini(self._language)
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_gemini_api_test(error))
            return
        self.after(0, lambda: self._finish_gemini_api_test(None))

    def _finish_gemini_api_test(self, error: Exception | None) -> None:
        self._api_test_running = False
        self.api_test_button.configure(state="normal", text="Test API")
        self._update_credit_display()
        if error is not None:
            self._gemini_connected = False
            self._set_connection_status("●  Gemini API test failed", "#e07a68")
            details = (
                str(error)
                if isinstance(error, BackendRequestError)
                else describe_gemini_error(error, self._language)
            )
            self._set_status(details)
            messagebox.showerror("Gemini API test failed", details, parent=self)
            return
        self._gemini_connected = True
        self._set_connection_status("●  Gemini Neural Connected", "#d48c51")
        self._set_status(f"Gemini API is working with {MODEL_NAME}.")

    def _on_enter(self, event: tk.Event) -> str | None:
        if event.state & 0x0001:
            return None
        self._send_message()
        return "break"

    def _send_message(self) -> None:
        if self._busy or self._api_test_running:
            return
        if self._credit_balance < 5:
            self._refresh_credit_balance()
            if self._credit_balance < 5:
                self._add_message("assistant", self._credit_locked_message())
                self._set_status(self._credit_locked_message())
                return
        message = self.input_field.get("1.0", "end").strip()
        image_paths = list(self._selected_images)
        if not message and not image_paths:
            return
        if image_paths and not message:
            message = "Please describe and analyze the attached image."
        self.input_field.delete("1.0", "end")
        self._add_message("user", message, image_paths=image_paths)
        if image_paths:
            self._selected_images.clear()
            self._refresh_attachments_label()

        if not image_paths:
            try:
                action = self._dispatch_intent(message)
            except DesktopActionError as exc:
                self._add_message("assistant", f"That action could not be completed: {exc}")
                self._set_status("The local action failed.")
                return
            if action is not None:
                self._add_message("assistant", action)
                self._speak_if_enabled(action)
                return

        if self._backend is None:
            reply = (
                self._backend_error
                or "The local AI backend is unavailable. Restart the app."
            )
            self._add_message("assistant", reply)
            self._set_status("The local AI backend is unavailable.")
            return

        self._busy = True
        self.send_button.configure(state="disabled", text="...")
        self.api_test_button.configure(state="disabled")
        self.attach_button.configure(state="disabled")
        self.capture_attach_button.configure(state="disabled")
        self.voice_button.configure(state="disabled")
        self._set_connection_status("●  Connecting to Gemini…", "#d48c51")
        self._set_status(
            "Analyzing image and thinking…" if image_paths else "Thinking…"
        )
        self._show_typing_indicator()
        threading.Thread(
            target=self._request_gemini,
            args=(message, image_paths, list(self._history)),
            daemon=True,
        ).start()

    def _request_gemini(
        self,
        message: str,
        image_paths: list[Path],
        history: list[dict[str, str]],
    ) -> None:
        try:
            if self._backend is None:
                raise BackendRequestError(
                    self._backend_error
                    or "The local AI backend is unavailable. Restart the app."
                )
            result = self._backend.chat(
                message,
                history,
                image_paths,
                self._language,
            )
            reply = result["reply"]
            self.after(
                0,
                lambda: self._finish_gemini(
                    reply,
                    None,
                    message,
                    image_paths,
                    credit_balance=result,
                ),
            )
        except Exception as exc:
            self.after(
                0,
                lambda error=exc: self._finish_gemini(
                    None, error, message, image_paths
                ),
            )

    def _finish_gemini(
        self,
        reply: str | None,
        error: Exception | None,
        message: str = "",
        image_paths: list[Path] | None = None,
        credit_balance: dict[str, Any] | None = None,
    ) -> None:
        self._busy = False
        self._hide_typing_indicator()
        self.api_test_button.configure(state="normal")
        self.attach_button.configure(state="normal")
        self.capture_attach_button.configure(state="normal")
        self.voice_button.configure(state="normal")
        if credit_balance is not None:
            self._apply_credit_balance(credit_balance)
        if error is not None:
            if image_paths:
                self._selected_images = list(image_paths)
                self._refresh_attachments_label()
            if message:
                self.input_field.insert("1.0", message)
            self._gemini_connected = False
            self._set_connection_status("●  Gemini Neural Disconnected", "#a49a94")
            is_locked = (
                isinstance(error, BackendRequestError)
                and error.status_code == 429
                and isinstance(error.detail, dict)
                and error.detail.get("locked") is True
            )
            if isinstance(error, BackendRequestError) and error.status_code == 429:
                if isinstance(error.detail, dict):
                    self._apply_credit_balance(error.detail)
                safe_message = (
                    self._credit_locked_message()
                    if is_locked
                    else str(error)
                )
            else:
                safe_message = (
                    str(error)
                    if isinstance(error, BackendRequestError)
                    else describe_gemini_error(error, self._language)
                )
            self._add_message("assistant", safe_message)
            self._set_status(
                self._credit_locked_message()
                if is_locked
                else "The Gemini request failed."
            )
            self._update_credit_display()
            return
        if reply is not None:
            history_message = message
            if image_paths:
                attached_names = ", ".join(path.name for path in image_paths)
                history_message = f"{message}\n[Images attached: {attached_names}]"
            self._history.extend(
                [
                    {"role": "user", "text": history_message},
                    {"role": "model", "text": reply},
                ]
            )
            self._history = self._history[-40:]
            self._gemini_connected = True
            self._set_connection_status("●  Gemini Neural Connected", "#d48c51")
            self._add_message("assistant", reply)
            self._set_status("Response received.")
            self._speak_if_enabled(reply)
        self._update_credit_display()

    def _dispatch_intent(self, message: str) -> str | None:
        normalized = " ".join(
            message.lower().strip().strip(" .!?،؟").split()
        )
        if normalized in {
            "clean desktop",
            "organize desktop",
            "clean my desktop",
            "organize my desktop",
        }:
            return self._clean_desktop()
        if normalized in {
            "capture screen",
            "take screenshot",
            "take a screenshot",
            "screenshot",
            "capture my screen",
        }:
            return self._capture_screen()
        app_commands = {
            "open browser": "browser",
            "launch browser": "browser",
            "open chrome": "browser",
            "open text editor": "notepad",
            "open notepad": "notepad",
            "open calculator": "calculator",
            "open file explorer": "explorer",
        }
        app = app_commands.get(normalized)
        if app:
            self._launch(app)
            return f"Opened {app}."
        return None

    def _clean_desktop(self) -> str:
        preview = organize_preview(get_desktop_path())
        if not preview:
            self._set_status("Desktop is already organized.")
            return "Your desktop has no files that need organizing."

        summary = "\n".join(
            f"• {item.source.name} → {item.destination.parent.name}/"
            for item in preview[:12]
        )
        if len(preview) > 12:
            summary += f"\n…and {len(preview) - 12} more file(s)."
        approved = messagebox.askyesno(
            "Organize desktop?",
            "This will move files into category folders. Nothing will be deleted.\n\n"
            f"{summary}\n\nContinue?",
            parent=self,
        )
        if not approved:
            self._set_status("Desktop organization cancelled.")
            return "Desktop organization cancelled. No files were moved."
        moved = clean_desktop(preview)
        self._set_status(f"Organized {len(moved)} desktop file(s).")
        return f"Done — organized {len(moved)} file(s) into folders. Nothing was deleted."

    def _choose_images(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Choose images to ask Gemini about",
            filetypes=[
                ("Supported images", "*.png *.jpg *.jpeg *.webp *.heic *.heif"),
                ("All files", "*.*"),
            ],
        )
        self._add_image_paths([Path(path) for path in paths])

    def _paste_clipboard_image(self, _event: tk.Event) -> str | None:
        try:
            clipboard_image = ImageGrab.grabclipboard()
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not read the clipboard image: {exc}")
            return None
        if not isinstance(clipboard_image, Image.Image):
            return None
        if self._busy or self._api_test_running:
            self._set_status("Wait for the current request to finish before attaching an image.")
            return "break"
        if len(self._selected_images) >= MAX_IMAGE_ATTACHMENTS:
            self._set_status(
                f"Up to {MAX_IMAGE_ATTACHMENTS} images can be attached per message."
            )
            return "break"
        try:
            path = save_clipboard_image(
                clipboard_image,
                PREFERENCES_FILE.parent / "clipboard",
                preserve_paths=set(self._selected_images),
            )
        except ValueError as exc:
            self._set_status(str(exc))
            messagebox.showerror("Could not paste image", str(exc), parent=self)
            return "break"
        self._add_image_paths([path])
        self._set_status("Clipboard image attached.")
        return "break"

    def _add_image_paths(self, paths: list[Path]) -> None:
        accepted = list(self._selected_images)
        errors: list[str] = []
        for path in paths:
            if path in accepted:
                continue
            if len(accepted) >= MAX_IMAGE_ATTACHMENTS:
                errors.append(f"Up to {MAX_IMAGE_ATTACHMENTS} images can be attached per message.")
                break
            try:
                validate_image(path)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            accepted.append(path)

        self._selected_images = accepted
        self._refresh_attachments_label()
        if errors:
            messagebox.showerror(
                "Some images could not be attached",
                "\n".join(errors),
                parent=self,
            )
        elif paths and accepted:
            self._set_status(
                f"{len(accepted)} image(s) attached. Gemini will receive them when you send."
            )

    def _refresh_attachments_label(self) -> None:
        if self._selected_images:
            names = ", ".join(path.name for path in self._selected_images)
            if len(names) > 46:
                names = names[:43] + "..."
            self.attachments_label.configure(
                text=f"{len(self._selected_images)} image(s): {names}",
                text_color="#d48c51",
            )
            try:
                with Image.open(self._selected_images[0]) as image:
                    preview = image.convert("RGBA")
                    preview.thumbnail((48, 48))
                self._attachment_preview_image = ctk.CTkImage(
                    light_image=preview,
                    dark_image=preview,
                    size=preview.size,
                )
                self.attachment_preview.configure(
                    image=self._attachment_preview_image,
                    text="",
                )
            except (OSError, Image.DecompressionBombError):
                self._attachment_preview_image = None
                self._clear_attachment_preview("▧")
            self.clear_attachments_button.configure(state="normal")
        else:
            self.attachments_label.configure(
                text="No images attached",
                text_color="#958a83",
            )
            self._attachment_preview_image = None
            self._clear_attachment_preview()
            self.clear_attachments_button.configure(state="disabled")

    def _clear_attachment_preview(self, text: str = "") -> None:
        self.attachment_preview.configure(image=None, text=text)
        # CTkLabel's image=None does not clear the underlying tkinter Label image.
        self.attachment_preview._label.configure(image="")

    def _open_attachment_preview(self, _event: tk.Event | None = None) -> None:
        if self._selected_images:
            self._show_image_preview(self._selected_images[0])

    def _show_image_preview(self, image_path: Path) -> None:
        if self._preview_window is not None and self._preview_window.winfo_exists():
            self._preview_window.focus()
            return
        try:
            with Image.open(image_path) as source:
                preview = source.convert("RGB")
                preview.thumbnail((1000, 720))
        except (OSError, Image.DecompressionBombError) as exc:
            messagebox.showerror(
                "Could not preview image",
                str(exc),
                parent=self,
            )
            return
        window = ctk.CTkToplevel(self)
        self._preview_window = window
        window.title("Image preview")
        window.geometry(f"{preview.width + 32}x{preview.height + 64}")
        window.transient(self)
        self._original_window_titles[window] = "Image preview"
        self._preview_window_image = ctk.CTkImage(
            light_image=preview,
            dark_image=preview,
            size=preview.size,
        )
        ctk.CTkLabel(window, text="", image=self._preview_window_image).pack(
            fill="both",
            expand=True,
            padx=16,
            pady=16,
        )
        self._register_localizable_widgets(window)
        self._apply_language()
        self._apply_theme()

    def _clear_image_attachments(self) -> None:
        self._selected_images.clear()
        self._refresh_attachments_label()
        self._set_status("Removed image attachments.")

    def _capture_and_attach(self) -> None:
        self.capture_attach_button.configure(state="disabled", text="Wait…")
        self._set_status("Switching to the previous window to capture its screen…")
        self.withdraw()
        self.after(900, self._finish_screenshot_attachment)

    def _finish_screenshot_attachment(self) -> None:
        try:
            path = take_screenshot(get_desktop_path())
        except DesktopActionError as exc:
            self.deiconify()
            self.focus_force()
            self.capture_attach_button.configure(state="normal", text="▧ Screen")
            self._set_status("Screenshot capture failed.")
            messagebox.showerror("Could not capture screen", str(exc), parent=self)
            return
        self.deiconify()
        self.focus_force()
        self.capture_attach_button.configure(state="normal", text="▧ Screen")
        self._add_image_paths([path])
        self._set_status(
            "Screenshot of the previous window saved and attached. Add a question, then send."
        )

    def _capture_screen(self) -> str:
        path = take_screenshot(get_desktop_path())
        self._set_status(f"Screenshot saved to {path.name}.")
        return f"Screenshot saved on your desktop as {path.name}."

    def _get_startup_enabled(self) -> bool:
        try:
            return is_windows_startup_enabled()
        except OSError as exc:
            self.after(
                300,
                lambda error=exc: messagebox.showerror(
                    "Startup setting unavailable", str(error), parent=self
                ),
            )
            return False

    def _toggle_windows_startup(self) -> None:
        try:
            set_windows_startup_enabled(
                self.startup_enabled.get(),
                Path(__file__).resolve(),
            )
        except (OSError, ImportError) as exc:
            self.startup_enabled.set(not self.startup_enabled.get())
            messagebox.showerror(
                "Could not update startup setting",
                str(exc),
                parent=self,
            )
            return
        state = "enabled" if self.startup_enabled.get() else "disabled"
        self._set_status(f"Start with Windows {state}.")

    def _refresh_shortcut_buttons(self) -> None:
        for widget in self.shortcut_buttons.winfo_children():
            widget.destroy()
        if not self._shortcuts:
            ctk.CTkLabel(
                self.shortcut_buttons,
                text="No shortcuts yet",
                anchor="w",
                text_color="#746b65",
                font=_font(size=11),
            ).pack(fill="x", padx=4, pady=4)
            if hasattr(self, "status_label"):
                self._apply_theme()
            return
        for index, shortcut in enumerate(self._shortcuts):
            ctk.CTkButton(
                self.shortcut_buttons,
                text=f"↗   {shortcut['name']}",
                command=lambda selected=index: self._run_sidebar_action(
                    lambda: self._launch_shortcut(selected)
                ),
                anchor="w",
                height=38,
                corner_radius=10,
                fg_color="#1f1815",
                hover_color="#2b211b",
                text_color="#e8e2de",
                border_width=1,
                border_color="#2c2521",
            ).pack(fill="x", pady=3)
        if hasattr(self, "status_label"):
            self._apply_theme()

    def _launch_shortcut(self, index: int) -> None:
        shortcut = self._shortcuts[index]
        targets = shortcut_targets_to_open(
            shortcut["targets"],
            shortcut.get("max_open", len(shortcut["targets"])),
        )
        launched: list[str] = []
        for target in targets:
            try:
                launch_target(target)
                launched.append(target)
            except DesktopActionError as exc:
                partial = (
                    f" Opened: {', '.join(launched)}."
                    if launched
                    else ""
                )
                raise DesktopActionError(
                    f"Shortcut '{shortcut['name']}' stopped at '{target}': {exc}.{partial}"
                ) from exc
        self._set_status(
            f"Opened shortcut '{shortcut['name']}' ({len(launched)} items)."
        )

    def _open_shortcut_editor(self) -> None:
        if self._shortcut_editor is not None and self._shortcut_editor.winfo_exists():
            self._shortcut_editor.focus()
            return

        editor = ctk.CTkToplevel(self)
        editor.title("My shortcuts")
        editor.geometry("680x700")
        editor.minsize(560, 600)
        editor.configure(fg_color="#0f0d0c")
        editor.transient(self)
        editor.grid_columnconfigure(0, weight=1)
        editor.grid_rowconfigure(2, weight=1)
        self._shortcut_editor = editor
        self._original_window_titles[editor] = "My shortcuts"
        self._shortcut_editor_index: int | None = None
        self._shortcut_max_open_var = tk.StringVar(value="1")

        ctk.CTkLabel(
            editor,
            text="Build a one-click launch",
            font=_font(size=20, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")
        ctk.CTkLabel(
            editor,
            text="Choose a saved shortcut to edit, or create a new one.",
            font=_font(size=11),
            text_color="#958a83",
        ).grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        list_panel = ctk.CTkScrollableFrame(
            editor,
            height=130,
            fg_color="#171412",
            corner_radius=12,
        )
        list_panel.grid(row=2, column=0, padx=20, pady=8, sticky="nsew")
        self._shortcut_list_panel = list_panel

        form = ctk.CTkFrame(editor, fg_color="transparent")
        form.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            form,
            text="Shortcut name",
            text_color="#b9ada5",
            font=_font(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self._shortcut_name_entry = ctk.CTkEntry(
            form,
            placeholder_text="e.g. Coding time",
            fg_color="#171412",
            border_color="#342a24",
        )
        self._shortcut_name_entry.grid(row=1, column=0, pady=(5, 12), sticky="ew")
        target_actions = ctk.CTkFrame(form, fg_color="transparent")
        target_actions.grid(row=2, column=0, sticky="ew")
        target_actions.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            target_actions,
            text="Apps or websites — one per line",
            text_color="#b9ada5",
            font=_font(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            target_actions,
            text="Installed apps…",
            width=116,
            command=self._open_installed_app_picker,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#d48c51",
        ).grid(row=0, column=1, padx=(4, 0), sticky="e")
        ctk.CTkButton(
            target_actions,
            text="Browse .exe",
            width=94,
            command=self._browse_shortcut_executable,
            fg_color="#2b211b",
            hover_color="#493326",
            text_color="#d48c51",
        ).grid(row=0, column=2, padx=(6, 0), sticky="e")
        target_row = ctk.CTkFrame(form, fg_color="transparent")
        target_row.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        target_row.grid_columnconfigure(0, weight=1)
        self._shortcut_targets_field = ctk.CTkTextbox(
            target_row,
            height=90,
            fg_color="#171412",
            border_width=1,
            border_color="#342a24",
            text_color="#ffffff",
            font=_font(size=12),
        )
        self._shortcut_targets_field.grid(row=0, column=0, sticky="ew")
        self._shortcut_targets_field.bind(
            "<KeyRelease>", self._update_shortcut_max_options
        )
        ctk.CTkLabel(
            form,
            text="Pick installed apps, or enter websites and .exe paths manually.",
            text_color="#746b65",
            font=_font(size=10),
        ).grid(row=4, column=0, pady=(5, 0), sticky="w")

        limit_row = ctk.CTkFrame(form, fg_color="transparent")
        limit_row.grid(row=5, column=0, pady=(12, 0), sticky="ew")
        ctk.CTkLabel(
            limit_row,
            text="How many apps to open? (from the top of the list)",
            text_color="#b9ada5",
            font=_font(size=11, weight="bold"),
        ).pack(side="left")
        self._shortcut_max_menu = ctk.CTkOptionMenu(
            limit_row,
            values=[str(value) for value in range(1, MAX_SHORTCUT_TARGETS + 1)],
            variable=self._shortcut_max_open_var,
            width=76,
            fg_color="#2b211b",
            button_color="#d48c51",
            button_hover_color="#b97842",
            dropdown_fg_color="#1f1815",
        )
        self._shortcut_max_menu.pack(side="left", padx=12)

        buttons = ctk.CTkFrame(editor, fg_color="transparent")
        buttons.grid(row=4, column=0, padx=20, pady=(4, 18), sticky="ew")
        ctk.CTkButton(
            buttons,
            text="New",
            width=72,
            command=self._new_shortcut,
            fg_color="#2b211b",
            hover_color="#493326",
        ).pack(side="left")
        ctk.CTkButton(
            buttons,
            text="Delete",
            width=78,
            command=self._delete_shortcut,
            fg_color="#42231f",
            hover_color="#66342c",
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            buttons,
            text="Save shortcut",
            width=126,
            command=self._save_shortcut_from_editor,
            fg_color="#d48c51",
            hover_color="#b97842",
            text_color="#100d0b",
            font=_font(weight="bold"),
        ).pack(side="right")

        self._refresh_shortcut_editor_list()
        editor.protocol("WM_DELETE_WINDOW", self._close_shortcut_editor)
        self._new_shortcut()
        self._register_localizable_widgets(editor)
        self._apply_language()
        self._apply_theme()

    def _refresh_shortcut_editor_list(self) -> None:
        if not self._shortcut_editor or not self._shortcut_editor.winfo_exists():
            return
        for widget in self._shortcut_list_panel.winfo_children():
            widget.destroy()
        for index, shortcut in enumerate(self._shortcuts):
            ctk.CTkButton(
                self._shortcut_list_panel,
                text=(
                    f"{shortcut['name']}  ·  "
                    f"{shortcut.get('max_open', len(shortcut['targets']))} apps"
                ),
                command=lambda selected=index: self._select_shortcut(selected),
                anchor="w",
                fg_color="#2b211b",
                hover_color="#34261e",
                text_color="#e8e2de",
            ).pack(fill="x", padx=4, pady=2)
        self._register_localizable_widgets(self._shortcut_list_panel)
        if hasattr(self, "status_label"):
            self._apply_language()
            self._apply_theme()

    def _select_shortcut(self, index: int) -> None:
        shortcut = self._shortcuts[index]
        self._shortcut_editor_index = index
        self._shortcut_name_entry.delete(0, "end")
        self._shortcut_name_entry.insert(0, shortcut["name"])
        self._shortcut_targets_field.delete("1.0", "end")
        self._shortcut_targets_field.insert(
            "1.0", "\n".join(shortcut["targets"])
        )
        self._update_shortcut_max_options()
        self._shortcut_max_open_var.set(
            str(shortcut.get("max_open", len(shortcut["targets"])))
        )

    def _new_shortcut(self) -> None:
        self._shortcut_editor_index = None
        self._shortcut_name_entry.delete(0, "end")
        self._shortcut_targets_field.delete("1.0", "end")
        self._update_shortcut_max_options()
        self._shortcut_max_open_var.set("1")
        self._shortcut_name_entry.focus()

    def _update_shortcut_max_options(self, _event: tk.Event | None = None) -> None:
        targets = [
            line.strip()
            for line in self._shortcut_targets_field.get("1.0", "end").splitlines()
            if line.strip()
        ]
        maximum = min(len(targets), MAX_SHORTCUT_TARGETS)
        values = [str(value) for value in range(1, max(1, maximum) + 1)]
        self._shortcut_max_menu.configure(values=values)
        try:
            current = int(self._shortcut_max_open_var.get())
        except ValueError:
            current = 1
        if current > max(1, maximum):
            self._shortcut_max_open_var.set(str(max(1, maximum)))

    def _browse_shortcut_executable(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self._shortcut_editor,
            title="Choose an application",
            filetypes=[("Windows applications", "*.exe"), ("All files", "*.*")],
        )
        if selected:
            current = self._shortcut_targets_field.get("1.0", "end").strip()
            separator = "\n" if current else ""
            self._shortcut_targets_field.insert("end", f"{separator}{selected}")
            self._update_shortcut_max_options()

    def _open_installed_app_picker(self) -> None:
        if self._installed_app_picker is not None and self._installed_app_picker.winfo_exists():
            self._installed_app_picker.focus()
            return

        apps = discover_installed_apps()
        if not apps:
            messagebox.showinfo(
                "No Start menu apps found",
                "No app shortcuts were found in the Windows Start menu. "
                "You can still use Browse .exe to choose an app.",
                parent=self._shortcut_editor,
            )
            return

        picker = ctk.CTkToplevel(self._shortcut_editor)
        picker.title("Choose installed apps")
        picker.geometry("520x620")
        picker.minsize(420, 420)
        picker.configure(fg_color="#0f0d0c")
        picker.transient(self._shortcut_editor)
        picker.grid_columnconfigure(0, weight=1)
        picker.grid_rowconfigure(2, weight=1)
        self._installed_app_picker = picker
        self._original_window_titles[picker] = "Choose installed apps"
        self._installed_apps = apps
        self._installed_app_selection = {
            line.strip()
            for line in self._shortcut_targets_field.get("1.0", "end").splitlines()
            if line.strip().lower().startswith("startmenu:")
        }
        self._installed_app_vars: dict[str, tk.BooleanVar] = {}

        ctk.CTkLabel(
            picker,
            text="Choose apps for this shortcut",
            font=_font(size=19, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=0, padx=18, pady=(18, 4), sticky="w")
        ctk.CTkLabel(
            picker,
            text="Apps with Start menu shortcuts are listed. Select as many as you need.",
            font=_font(size=10),
            text_color="#958a83",
        ).grid(row=1, column=0, padx=18, pady=(0, 10), sticky="w")

        toolbar = ctk.CTkFrame(picker, fg_color="transparent")
        toolbar.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="new")
        toolbar.grid_columnconfigure(0, weight=1)
        self._installed_app_search = ctk.CTkEntry(
            toolbar,
            placeholder_text="Search installed apps…",
            fg_color="#171412",
            border_color="#342a24",
        )
        self._installed_app_search.grid(row=0, column=0, sticky="ew")
        self._installed_app_search.bind(
            "<KeyRelease>", self._filter_installed_app_picker
        )
        ctk.CTkButton(
            toolbar,
            text="Select all",
            width=82,
            command=self._select_all_installed_apps,
            fg_color="#2b211b",
            hover_color="#493326",
        ).grid(row=0, column=1, padx=(8, 0))

        app_list = ctk.CTkScrollableFrame(
            picker,
            fg_color="#171412",
            corner_radius=12,
            scrollbar_button_color="#42352d",
            scrollbar_button_hover_color="#d48c51",
        )
        app_list.grid(row=3, column=0, padx=18, pady=4, sticky="nsew")
        picker.grid_rowconfigure(3, weight=1)
        self._installed_app_list = app_list

        footer = ctk.CTkFrame(picker, fg_color="transparent")
        footer.grid(row=4, column=0, padx=18, pady=(8, 16), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._installed_app_count_label = ctk.CTkLabel(
            footer,
            text="0 apps selected",
            anchor="w",
            text_color="#b9ada5",
            font=_font(size=11),
        )
        self._installed_app_count_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            footer,
            text="Add selected",
            width=120,
            command=self._add_selected_installed_apps,
            fg_color="#d48c51",
            hover_color="#b97842",
            text_color="#100d0b",
            font=_font(weight="bold"),
        ).grid(row=0, column=1, padx=(8, 0))
        picker.protocol("WM_DELETE_WINDOW", self._close_installed_app_picker)
        self._render_installed_apps()
        self._register_localizable_widgets(picker)
        self._apply_language()
        self._apply_theme()

    def _render_installed_apps(self) -> None:
        for widget in self._installed_app_list.winfo_children():
            widget.destroy()
        query = self._installed_app_search.get().strip().casefold()
        visible_apps = [
            app
            for app in self._installed_apps
            if query in app["name"].casefold()
        ]
        if not visible_apps:
            ctk.CTkLabel(
                self._installed_app_list,
                text="No matching apps found.",
                text_color="#958a83",
            ).pack(padx=10, pady=14, anchor="w")
        for app in visible_apps:
            target = app["target"]
            selected = tk.BooleanVar(
                value=target in self._installed_app_selection
            )
            self._installed_app_vars[target] = selected
            ctk.CTkCheckBox(
                self._installed_app_list,
                text=app["name"],
                variable=selected,
                command=lambda selected_target=target, variable=selected: (
                    self._update_installed_app_selection(
                        selected_target, variable.get()
                    )
                ),
                fg_color="#d48c51",
                hover_color="#b97842",
                text_color="#e8e2de",
                border_color="#6e5847",
            ).pack(fill="x", padx=10, pady=5, anchor="w")
        self._update_installed_app_count()
        if hasattr(self, "status_label"):
            self._apply_theme()

    def _update_installed_app_selection(self, target: str, selected: bool) -> None:
        if selected:
            if len(self._installed_app_selection) >= MAX_SHORTCUT_TARGETS:
                self._installed_app_vars[target].set(False)
                messagebox.showinfo(
                    "Shortcut app limit",
                    f"Choose up to {MAX_SHORTCUT_TARGETS} apps for each shortcut.",
                    parent=self._installed_app_picker,
                )
                return
            self._installed_app_selection.add(target)
        else:
            self._installed_app_selection.discard(target)
        self._update_installed_app_count()

    def _update_installed_app_count(self) -> None:
        self._installed_app_count_label.configure(
            text=f"{len(self._installed_app_selection)} apps selected"
        )

    def _filter_installed_app_picker(self, _event: tk.Event) -> None:
        self._render_installed_apps()

    def _select_all_installed_apps(self) -> None:
        query = self._installed_app_search.get().strip().casefold()
        matching_targets = [
            app["target"]
            for app in self._installed_apps
            if query in app["name"].casefold()
        ]
        available = max(
            0, MAX_SHORTCUT_TARGETS - len(self._installed_app_selection)
        )
        self._installed_app_selection.update(matching_targets[:available])
        self._render_installed_apps()

    def _add_selected_installed_apps(self) -> None:
        current = [
            line.strip()
            for line in self._shortcut_targets_field.get("1.0", "end").splitlines()
            if line.strip()
        ]
        existing = {target.casefold() for target in current}
        for app in self._installed_apps:
            target = app["target"]
            if target in self._installed_app_selection and target.casefold() not in existing:
                current.append(target)
                existing.add(target.casefold())
        if len(current) > MAX_SHORTCUT_TARGETS:
            messagebox.showerror(
                "Too many shortcut apps",
                f"A shortcut can contain up to {MAX_SHORTCUT_TARGETS} apps or websites.",
                parent=self._installed_app_picker,
            )
            return
        self._shortcut_targets_field.delete("1.0", "end")
        self._shortcut_targets_field.insert("1.0", "\n".join(current))
        self._update_shortcut_max_options()
        self._close_installed_app_picker()

    def _close_installed_app_picker(self) -> None:
        if self._installed_app_picker is not None:
            self._installed_app_picker.destroy()
            self._installed_app_picker = None

    def _save_shortcut_from_editor(self) -> None:
        name = self._shortcut_name_entry.get().strip()
        targets = [
            line.strip()
            for line in self._shortcut_targets_field.get("1.0", "end").splitlines()
            if line.strip()
        ]
        if not name or not targets:
            messagebox.showerror(
                "Shortcut details needed",
                "Enter a shortcut name and at least one app or website.",
                parent=self._shortcut_editor,
            )
            return
        if len(targets) > 12:
            messagebox.showerror(
                "Too many shortcut items",
                "A shortcut can contain up to 12 apps or websites.",
                parent=self._shortcut_editor,
            )
            return
        try:
            max_open = int(self._shortcut_max_open_var.get())
        except ValueError:
            messagebox.showerror(
                "Choose how many apps to open",
                "Select a valid app count from the menu.",
                parent=self._shortcut_editor,
            )
            return
        if not 1 <= max_open <= min(MAX_SHORTCUT_TARGETS, len(targets)):
            messagebox.showerror(
                "App count is larger than the shortcut",
                f"Choose between 1 and {len(targets)} app(s) to open.",
                parent=self._shortcut_editor,
            )
            return
        try:
            for target in targets:
                validate_shortcut_target(target)
        except DesktopActionError as exc:
            messagebox.showerror(
                "Shortcut target is not valid",
                str(exc),
                parent=self._shortcut_editor,
            )
            return
        if any(
            index != self._shortcut_editor_index
            and shortcut["name"].casefold() == name.casefold()
            for index, shortcut in enumerate(self._shortcuts)
        ):
            messagebox.showerror(
                "Shortcut name already exists",
                "Choose a unique shortcut name.",
                parent=self._shortcut_editor,
            )
            return

        shortcut = {"name": name, "targets": targets, "max_open": max_open}
        updated = list(self._shortcuts)
        if self._shortcut_editor_index is None:
            updated.append(shortcut)
        else:
            updated[self._shortcut_editor_index] = shortcut
        try:
            save_shortcuts(updated, SHORTCUTS_FILE)
        except ValueError as exc:
            messagebox.showerror("Could not save shortcut", str(exc), parent=self._shortcut_editor)
            return
        self._shortcuts = updated
        self._refresh_shortcut_buttons()
        self._refresh_shortcut_editor_list()
        self._shortcut_editor_index = updated.index(shortcut)
        self._set_status(f"Saved shortcut '{name}'.")

    def _delete_shortcut(self) -> None:
        if self._shortcut_editor_index is None:
            return
        shortcut = self._shortcuts[self._shortcut_editor_index]
        if not messagebox.askyesno(
            "Delete shortcut?",
            f"Delete '{shortcut['name']}'?",
            parent=self._shortcut_editor,
        ):
            return
        updated = [
            item
            for index, item in enumerate(self._shortcuts)
            if index != self._shortcut_editor_index
        ]
        try:
            save_shortcuts(updated, SHORTCUTS_FILE)
        except ValueError as exc:
            messagebox.showerror("Could not delete shortcut", str(exc), parent=self._shortcut_editor)
            return
        self._shortcuts = updated
        self._refresh_shortcut_buttons()
        self._refresh_shortcut_editor_list()
        self._new_shortcut()

    def _close_shortcut_editor(self) -> None:
        if self._shortcut_editor is not None:
            self._shortcut_editor.destroy()
            self._shortcut_editor = None

    def _run_sidebar_action(self, action: Any) -> None:
        try:
            action()
        except DesktopActionError as exc:
            self._set_status("The local action failed.")
            messagebox.showerror("Desktop action failed", str(exc), parent=self)

    def _launch(self, app: str) -> None:
        if app == "browser":
            if not webbrowser.open("https://www.google.com", new=2):
                raise DesktopActionError("Could not open your default browser.")
            self._set_status("Opened your default browser.")
            return
        launch_program(app)
        self._set_status(f"Opened {app}.")

    def _listen(self) -> None:
        try:
            import speech_recognition as sr
        except ImportError:
            messagebox.showerror(
                "Voice recognition unavailable",
                "Install the project requirements to enable voice recognition.",
                parent=self,
            )
            return
        self.voice_button.configure(state="disabled", text="…")
        self._set_status("Listening — speak now (up to 8 seconds)…")
        threading.Thread(target=self._recognize_speech, args=(sr,), daemon=True).start()

    def _recognize_speech(self, sr: Any) -> None:
        try:
            import sounddevice as sd

            sample_rate = 16000
            recording = sd.rec(
                int(8 * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
            )
            sd.wait()
            recognizer = sr.Recognizer()
            audio = sr.AudioData(recording.tobytes(), sample_rate, 2)
            text = recognizer.recognize_google(
                audio,
                language=speech_language(self._language),
            )
            self.after(0, lambda: self._finish_listening(text, None))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_listening(None, error))

    def _finish_listening(self, text: str | None, error: Exception | None) -> None:
        self.voice_button.configure(state="normal", text="🎙")
        if error is not None:
            self._set_status("Voice recognition failed.")
            if error.__class__.__name__ == "UnknownValueError":
                details = "I couldn't make out the speech. Try again in a quieter place."
            elif error.__class__.__name__ == "RequestError":
                details = (
                    "The speech-recognition service could not be reached. "
                    "Check your internet connection."
                )
            else:
                details = (
                    f"{error}\n\nCheck that a microphone is connected and enabled "
                    "in Windows microphone privacy settings."
                )
            messagebox.showerror(
                "Could not recognize speech",
                details,
                parent=self,
            )
            return
        if text:
            self.input_field.insert("end", text)
            self._send_message()

    def _speak_if_enabled(self, text: str) -> None:
        if not self._voice_output.get():
            return
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text: str) -> None:
        try:
            import pyttsx3

            language = speech_language(self._language)
            with TTS_LOCK:
                engine = pyttsx3.init()
                voices = engine.getProperty("voices")
                language_prefix = language.split("-", 1)[0].casefold()
                selected_voice = next(
                    (
                        voice
                        for voice in voices
                        if language_prefix
                        in " ".join(
                            [
                                str(voice.name),
                                str(voice.id),
                                *[
                                    item.decode("ascii", errors="ignore")
                                    if isinstance(item, bytes)
                                    else str(item)
                                    for item in getattr(voice, "languages", [])
                                ],
                            ]
                        ).casefold()
                    ),
                    None,
                )
                if selected_voice is not None:
                    engine.setProperty("voice", selected_voice.id)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            if selected_voice is None and language_prefix != "en":
                self.after(
                    0,
                    lambda: self._set_status(
                        f"No installed {language} speech voice; using the system default."
                    ),
                )
        except Exception as exc:
            self.after(
                0,
                lambda error=exc: self._set_status(f"Voice output failed: {error}"),
            )

    def _show_typing_indicator(self) -> None:
        if self._typing_indicator is not None:
            return
        self._typing_indicator = ctk.CTkFrame(
            self.chat,
            fg_color="#1a1816",
            corner_radius=14,
            border_width=1,
            border_color="#342a24",
        )
        self._typing_indicator.grid(
            row=len(self.chat.winfo_children()),
            column=0,
            padx=14,
            pady=8,
            sticky="w",
        )
        ctk.CTkLabel(
            self._typing_indicator,
            text="AI HELP YOU",
            font=_font(size=9, weight="bold"),
            text_color="#b98760",
        ).pack(anchor="w", padx=14, pady=(8, 0))
        self._typing_label = ctk.CTkLabel(
            self._typing_indicator,
            text="Gemini is thinking ·",
            font=_font(size=12),
            text_color="#d48c51",
        )
        self._typing_label.pack(anchor="w", padx=14, pady=(1, 8))
        self._typing_dots = 1
        self._animate_typing_indicator()
        self.after(40, self._scroll_chat_to_end)
        self._apply_theme()

    def _animate_typing_indicator(self) -> None:
        if self._typing_indicator is None:
            return
        dots = "." * self._typing_dots
        self._typing_label.configure(text=f"Gemini is thinking {dots}")
        self._typing_dots = self._typing_dots % 3 + 1
        self._typing_after_id = self.after(320, self._animate_typing_indicator)

    def _hide_typing_indicator(self) -> None:
        if self._typing_after_id is not None:
            self.after_cancel(self._typing_after_id)
            self._typing_after_id = None
        if self._typing_indicator is not None:
            self._typing_indicator.destroy()
            self._typing_indicator = None

    def _add_message(
        self,
        role: str,
        text: str,
        image_paths: list[Path] | None = None,
    ) -> None:
        is_user = role == "user"
        wrapper = ctk.CTkFrame(self.chat, fg_color="transparent")
        wrapper.grid(
            row=len(self.chat.winfo_children()),
            column=0,
            padx=14,
            pady=8,
            sticky="e" if is_user else "w",
        )
        bubble = ctk.CTkFrame(
            wrapper,
            fg_color="#36271e" if is_user else "#1a1816",
            corner_radius=14,
            border_width=1 if not is_user else 0,
            border_color="#2c2521",
        )
        bubble.pack(anchor="e" if is_user else "w")
        speaker_label = ctk.CTkLabel(
            bubble,
            text=self._tr("YOU" if is_user else "AI HELP YOU"),
            font=_font(size=9, weight="bold"),
            text_color="#d48c51" if is_user else "#b98760",
        )
        speaker_label.pack(anchor="w", padx=14, pady=(9, 0))
        self._original_widget_texts[speaker_label] = (
            "YOU" if is_user else "AI HELP YOU"
        )
        ctk.CTkLabel(
            bubble,
            text=text,
            justify="right" if self._language == "العربية" else "left",
            anchor="e" if self._language == "العربية" else "w",
            wraplength=680,
            font=_font(size=14),
            text_color="#f0eeec",
        ).pack(anchor="w", padx=14, pady=(3, 11))
        if image_paths:
            image_row = ctk.CTkFrame(bubble, fg_color="transparent")
            image_row.pack(anchor="w", padx=10, pady=(0, 10))
            for image_path in image_paths:
                tile = ctk.CTkFrame(
                    image_row,
                    fg_color="#2b211b",
                    corner_radius=10,
                )
                tile.pack(side="left", padx=4)
                try:
                    with Image.open(image_path) as source:
                        thumbnail = source.convert("RGB")
                        thumbnail.thumbnail((112, 82))
                    image = ctk.CTkImage(
                        light_image=thumbnail,
                        dark_image=thumbnail,
                        size=thumbnail.size,
                    )
                    self._message_image_refs.append(image)
                    image_label = ctk.CTkLabel(tile, text="", image=image)
                    image_label.pack(padx=5, pady=(5, 2))
                    image_label.bind(
                        "<Button-1>",
                        lambda _event, path=image_path: self._show_image_preview(path),
                    )
                except (OSError, Image.DecompressionBombError):
                    ctk.CTkLabel(
                        tile,
                        text="Image unavailable",
                        width=112,
                        height=82,
                        font=_font(size=10),
                        text_color="#b9ada5",
                    ).pack(padx=5, pady=(5, 2))
                ctk.CTkLabel(
                    tile,
                    text=image_path.name,
                    width=122,
                    wraplength=112,
                    anchor="center",
                    font=_font(size=9),
                    text_color="#b9ada5",
                ).pack(padx=4, pady=(0, 5))
        self._animate_message_entrance(wrapper, 0)
        self.after(40, self._scroll_chat_to_end)
        if hasattr(self, "status_label"):
            self._apply_theme()

    def _animate_message_entrance(
        self, widget: ctk.CTkFrame, step: int
    ) -> None:
        if not widget.winfo_exists():
            return
        inset = max(0, 5 - step)
        widget.grid_configure(pady=(inset, 8))
        if step < 5:
            self.after(
                16,
                lambda: self._animate_message_entrance(widget, step + 1),
            )

    def _scroll_chat_to_end(self) -> None:
        self.chat._parent_canvas.yview_moveto(1.0)

    def _set_status(self, text: str) -> None:
        self._status_source = text
        self.status_label.configure(text=self._tr(text))


if __name__ == "__main__":
    AIToolProMax(startup_mode="--startup" in sys.argv[1:]).mainloop()
