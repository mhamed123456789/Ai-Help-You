from __future__ import annotations

from io import BytesIO
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_REQUEST_SIZE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_ATTACHMENTS = 4
MAX_GEMINI_IMAGE_DIMENSION = 1024
MAX_CLIPBOARD_CACHE_FILES = 4
MAX_CLIPBOARD_IMAGE_PIXELS = 20_000_000
MAX_SHORTCUT_TARGETS = 12
PREFERENCES_FILE = (
    Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    / "Ai Tool"
    / "preferences.json"
)
IMAGE_MIME_TYPES = {
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
SHORTCUTS_FILE = (
    Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    / "Ai Tool"
    / "shortcuts.json"
)
STARTUP_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "Ai Tool"
SUPPORTED_LANGUAGES = {
    "English": "en-US",
    "Français": "fr-FR",
    "العربية": "ar-TN",
}
THEME_SCHEDULE = {"dark_start_hour": 19, "light_start_hour": 7}
THEME_COLOR_MAPS = {
    "dark": {
        "#0a0a0a": "#0a0908",
        "#0f0d0c": "#0f0d0c",
        "#100d0b": "#100d0b",
        "#100f0e": "#100f0e",
        "#120f0e": "#120f0e",
        "#171412": "#171412",
        "#1a1816": "#1a1816",
        "#1f1815": "#1f1815",
        "#2b211b": "#2b211b",
        "#2c2521": "#2c2521",
        "#2c2a24": "#2c2a24",
        "#34261e": "#34261e",
        "#342a24": "#342a24",
        "#36271e": "#36271e",
        "#42231f": "#42231f",
        "#42352d": "#42352d",
        "#493326": "#493326",
        "#66342c": "#66342c",
        "#6e5847": "#6e5847",
        "#746b65": "#746b65",
        "#926744": "#926744",
        "#958a83": "#958a83",
        "#a49a94": "#a49a94",
        "#b9ada5": "#b9ada5",
        "#b97842": "#b97842",
        "#b98760": "#b98760",
        "#d48c51": "#d48c51",
        "#e07a68": "#e07a68",
        "#e0a168": "#e0a168",
        "#e5b07f": "#e5b07f",
        "#e8e2de": "#e8e2de",
        "#f0eeec": "#f0eeec",
        "#ffffff": "#ffffff",
    },
    "light": {
        "#0a0a0a": "#fbf8f4",
        "#0f0d0c": "#ffffff",
        "#100d0b": "#ffffff",
        "#100f0e": "#efe7df",
        "#120f0e": "#eee9e4",
        "#171412": "#ffffff",
        "#1a1816": "#f5eee7",
        "#1f1815": "#f1e7de",
        "#2b211b": "#f1e7de",
        "#2c2521": "#e6ddd5",
        "#2c2a24": "#e6ddd5",
        "#34261e": "#e8d8c9",
        "#342a24": "#ded4cb",
        "#36271e": "#ead6c2",
        "#42231f": "#f2dfdb",
        "#42352d": "#cfc2b7",
        "#493326": "#dfc5ad",
        "#66342c": "#e4c2b9",
        "#6e5847": "#a68b73",
        "#746b65": "#71665d",
        "#926744": "#ab6736",
        "#958a83": "#665b52",
        "#a49a94": "#6f665f",
        "#b9ada5": "#534a43",
        "#b97842": "#a96633",
        "#b98760": "#936340",
        "#d48c51": "#9a5726",
        "#e07a68": "#b64230",
        "#e0a168": "#95602e",
        "#e5b07f": "#a76632",
        "#e8e2de": "#241d18",
        "#f0eeec": "#211a15",
        "#ffffff": "#211a15",
    },
}
UI_TRANSLATIONS = {
    "Français": {
        "AI HELP YOU": "AI HELP YOU",
        "⚙   Settings": "⚙   Paramètres",
        "DESKTOP INTELLIGENCE HUB": "ASSISTANT INTELLIGENT",
        "QUICK ACTIONS": "ACTIONS RAPIDES",
        "MY SHORTCUTS": "MES RACCOURCIS",
        "⌘   Clean desktop": "⌘   Ranger le bureau",
        "◉   Open browser": "◉   Ouvrir le navigateur",
        "▤   Open text editor": "▤   Ouvrir l’éditeur de texte",
        "⚙   Open calculator": "⚙   Ouvrir la calculatrice",
        "+ Create / edit shortcuts": "+ Créer / modifier les raccourcis",
        "Start with Windows": "Démarrer avec Windows",
        "Settings": "Paramètres",
        "Open AI Help You automatically when you sign in.": "Ouvrir AI Help You automatiquement à la connexion.",
        "Appearance": "Apparence",
        "Language": "Langue",
        "Test API": "Tester l’API",
        "Auto": "Automatique",
        "Dark": "Sombre",
        "Light": "Clair",
        "Clipboard image attached.": "Image du presse-papiers jointe.",
        "Local actions stay on your PC.\nGemini needs an API key.": "Les actions restent locales.\nGemini nécessite une clé API.",
        "Testing…": "Test en cours…",
        "Wait…": "Patientez…",
        "My shortcuts": "Mes raccourcis",
        "Image preview": "Aperçu de l’image",
        "Gemini SDK unavailable": "SDK Gemini indisponible",
        "Gemini API key not found": "Clé API Gemini introuvable",
        "AI Help You": "AI Help You",
        "No images attached": "Aucune image jointe",
        "＋ Image": "＋ Image",
        "▧ Screen": "▧ Écran",
        "Clear": "Effacer",
        "Send": "Envoyer",
        "Voice output": "Réponse vocale",
        "Enter to send · Shift+Enter for a new line": "Entrée pour envoyer · Maj+Entrée pour une nouvelle ligne",
        "Gemini is thinking ·": "Gemini réfléchit ·",
        "Ready when you are.": "Prêt quand vous l’êtes.",
        "Thinking…": "Réflexion…",
        "Analyzing image and thinking…": "Analyse de l’image…",
        "Response received.": "Réponse reçue.",
        "Gemini Neural Disconnected": "Gemini déconnecté",
        "Gemini Neural Ready": "Gemini prêt",
        "Gemini Neural Connected": "Gemini connecté",
        "Gemini API test failed": "Échec du test Gemini",
        "Connecting to Gemini…": "Connexion à Gemini…",
        "Testing Gemini connection…": "Test de connexion Gemini…",
        "Gemini rejected the API key. Check your local .env value and key permissions.": "Gemini a refusé la clé API. Vérifiez la valeur dans votre fichier .env et les autorisations de la clé.",
        "Gemini is rate-limiting this key or its quota is exhausted. Check Google AI Studio.": "Gemini limite cette clé ou son quota est épuisé. Vérifiez Google AI Studio.",
        "Could not reach Gemini. Check your internet connection and try again.": "Impossible de joindre Gemini. Vérifiez votre connexion Internet et réessayez.",
        "Voice recognition failed.": "La reconnaissance vocale a échoué.",
        "Voice recognition failed": "La reconnaissance vocale a échoué",
        "Voice output failed": "Échec de la réponse vocale",
        "Clean desktop": "Ranger le bureau",
        "Open browser": "Ouvrir le navigateur",
        "Open text editor": "Ouvrir l’éditeur de texte",
        "Open calculator": "Ouvrir la calculatrice",
        "No shortcuts yet": "Aucun raccourci",
        "Build a one-click launch": "Créer un lancement en un clic",
        "Choose a saved shortcut to edit, or create a new one.": "Modifiez un raccourci ou créez-en un.",
        "Shortcut name": "Nom du raccourci",
        "Apps or websites — one per line": "Applications ou sites — un par ligne",
        "Installed apps…": "Applications installées…",
        "Browse .exe": "Choisir un .exe",
        "Pick installed apps, or enter websites and .exe paths manually.": "Choisissez des applications ou saisissez des sites et chemins .exe.",
        "How many apps to open? (from the top of the list)": "Nombre d’applications à ouvrir (dans l’ordre)",
        "New": "Nouveau",
        "Delete": "Supprimer",
        "Save shortcut": "Enregistrer",
        "Choose installed apps": "Choisir des applications",
        "Choose apps for this shortcut": "Choisissez les applications du raccourci",
        "Apps with Start menu shortcuts are listed. Select as many as you need.": "Applications avec raccourci du menu Démarrer. Sélectionnez celles voulues.",
        "Search installed apps…": "Rechercher des applications…",
        "Select all": "Tout sélectionner",
        "Add selected": "Ajouter la sélection",
        "No matching apps found.": "Aucune application trouvée.",
        "YOU": "VOUS",
    },
    "العربية": {
        "⚙   Settings": "⚙   الإعدادات",
        "DESKTOP INTELLIGENCE HUB": "مساعد سطح المكتب الذكي",
        "QUICK ACTIONS": "إجراءات سريعة",
        "MY SHORTCUTS": "اختصاراتي",
        "Start with Windows": "التشغيل مع Windows",
        "Settings": "الإعدادات",
        "Open AI Help You automatically when you sign in.": "تشغيل AI Help You تلقائيًا عند تسجيل الدخول.",
        "Appearance": "المظهر",
        "Language": "اللغة",
        "⌘   Clean desktop": "⌘   تنظيم سطح المكتب",
        "◉   Open browser": "◉   فتح المتصفح",
        "▤   Open text editor": "▤   فتح محرر النصوص",
        "⚙   Open calculator": "⚙   فتح الحاسبة",
        "+ Create / edit shortcuts": "+ إنشاء / تعديل الاختصارات",
        "Auto": "تلقائي",
        "Dark": "داكن",
        "Light": "فاتح",
        "Clipboard image attached.": "تم إرفاق صورة الحافظة.",
        "Local actions stay on your PC.\nGemini needs an API key.": "الإجراءات محلية على جهازك.\nGemini يحتاج مفتاح API.",
        "Your personal AI companion": "مساعدك الذكي الشخصي",
        "Test API": "اختبار API",
        "Testing…": "جارٍ الاختبار…",
        "Wait…": "انتظر…",
        "My shortcuts": "اختصاراتي",
        "Image preview": "معاينة الصورة",
        "Gemini SDK unavailable": "حزمة Gemini غير متاحة",
        "Gemini API key not found": "مفتاح Gemini API غير موجود",
        "AI Help You": "AI Help You",
        "No images attached": "لا توجد صور مرفقة",
        "＋ Image": "＋ صورة",
        "▧ Screen": "▧ الشاشة",
        "Clear": "مسح",
        "Send": "إرسال",
        "Voice output": "الرد الصوتي",
        "Enter to send · Shift+Enter for a new line": "Enter للإرسال · Shift+Enter لسطر جديد",
        "Gemini is thinking ·": "Gemini يفكر ·",
        "Ready when you are.": "أنا جاهز لمساعدتك.",
        "Thinking…": "جارٍ التفكير…",
        "Analyzing image and thinking…": "جارٍ تحليل الصورة والتفكير…",
        "Response received.": "تم استلام الرد.",
        "Gemini Neural Disconnected": "Gemini غير متصل",
        "Gemini Neural Ready": "Gemini جاهز",
        "Gemini Neural Connected": "Gemini متصل",
        "Gemini API test failed": "فشل اختبار Gemini",
        "Connecting to Gemini…": "جارٍ الاتصال بـ Gemini…",
        "Testing Gemini connection…": "جارٍ اختبار اتصال Gemini…",
        "Gemini rejected the API key. Check your local .env value and key permissions.": "رفض Gemini مفتاح API. تحقق من المفتاح في ملف .env والصلاحيات.",
        "Gemini is rate-limiting this key or its quota is exhausted. Check Google AI Studio.": "Gemini يحدّ من الطلبات أو انتهت الحصة. تحقق من Google AI Studio.",
        "Could not reach Gemini. Check your internet connection and try again.": "تعذّر الاتصال بـ Gemini. تحقق من الإنترنت وحاول مجددًا.",
        "Voice recognition failed.": "فشل التعرّف على الصوت.",
        "Voice recognition failed": "فشل التعرّف على الصوت",
        "Voice output failed": "فشل الرد الصوتي",
        "Clean desktop": "تنظيم سطح المكتب",
        "Open browser": "فتح المتصفح",
        "Open text editor": "فتح محرر النصوص",
        "Open calculator": "فتح الحاسبة",
        "No shortcuts yet": "لا توجد اختصارات",
        "Build a one-click launch": "أنشئ اختصارًا بنقرة واحدة",
        "Choose a saved shortcut to edit, or create a new one.": "اختر اختصارًا لتعديله أو أنشئ اختصارًا جديدًا.",
        "Shortcut name": "اسم الاختصار",
        "Apps or websites — one per line": "التطبيقات أو المواقع — عنصر في كل سطر",
        "Installed apps…": "التطبيقات المثبتة…",
        "Browse .exe": "اختيار ملف .exe",
        "Pick installed apps, or enter websites and .exe paths manually.": "اختر التطبيقات المثبتة أو أدخل المواقع ومسارات .exe.",
        "How many apps to open? (from the top of the list)": "عدد التطبيقات التي ستُفتح بالترتيب",
        "New": "جديد",
        "Delete": "حذف",
        "Save shortcut": "حفظ الاختصار",
        "Choose installed apps": "اختيار التطبيقات المثبتة",
        "Choose apps for this shortcut": "اختر تطبيقات هذا الاختصار",
        "Apps with Start menu shortcuts are listed. Select as many as you need.": "تظهر تطبيقات قائمة ابدأ. اختر التطبيقات التي تحتاجها.",
        "Search installed apps…": "ابحث عن التطبيقات…",
        "Select all": "تحديد الكل",
        "Add selected": "إضافة المحدد",
        "No matching apps found.": "لم يتم العثور على تطبيقات.",
        "AI HELP YOU": "مساعدك الذكي",
        "YOU": "أنت",
    },
}
THEME_PALETTES = {
    "dark": {
        "app_bg": "#0a0908",
        "sidebar_bg": "#120f0e",
        "panel_bg": "#100f0e",
        "surface": "#171412",
        "assistant_bubble": "#1a1816",
        "user_bubble": "#36271e",
        "accent": "#d48c51",
        "text": "#f0eeec",
        "muted": "#b9ada5",
        "border": "#342a24",
    },
    "light": {
        "app_bg": "#fbf8f4",
        "sidebar_bg": "#eee9e4",
        "panel_bg": "#efe7df",
        "surface": "#f5eee7",
        "assistant_bubble": "#f5eee7",
        "user_bubble": "#ead6c2",
        "accent": "#9a5726",
        "text": "#211a15",
        "muted": "#665b52",
        "border": "#ded4cb",
    },
}
DEFAULT_SHORTCUTS = [
    {"name": "Study setup", "targets": ["https://www.google.com", "code"]}
]


def build_user_content(text: str, image_paths: list[Path], sdk_types: Any) -> Any:
    images: list[tuple[str, bytes, str]] = []
    for path in image_paths:
        mime_type = validate_image(path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Could not read {path.name}: {exc}") from exc
        images.append((path.name, data, mime_type))
    return build_user_content_from_bytes(text, images, sdk_types)


def build_user_content_from_bytes(
    text: str,
    images: list[tuple[str, bytes, str]],
    sdk_types: Any,
    optimize_images: bool = True,
) -> Any:
    parts = [sdk_types.Part.from_text(text=text)]
    total_request_size = 0
    for name, data, mime_type in images:
        if mime_type not in IMAGE_MIME_TYPES.values():
            raise ValueError(f"{name} has an unsupported image format.")
        if len(data) > MAX_IMAGE_SIZE_BYTES:
            raise ValueError(f"{name} is larger than the 10 MB per-image limit.")
        if optimize_images:
            data, mime_type = prepare_image_bytes(name, data, mime_type)
        total_request_size += 4 * ((len(data) + 2) // 3)
        if total_request_size > MAX_IMAGE_REQUEST_SIZE_BYTES:
            raise ValueError("Selected images exceed the 20 MB encoded request limit.")
        parts.append(sdk_types.Part.from_bytes(data=data, mime_type=mime_type))
    return sdk_types.Content(role="user", parts=parts)


def prepare_image_bytes(
    name: str,
    data: bytes,
    mime_type: str,
) -> tuple[bytes, str]:
    if len(data) > MAX_IMAGE_SIZE_BYTES:
        raise ValueError(f"{name} is larger than the 10 MB per-image limit.")
    try:
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGB")
            image.thumbnail(
                (MAX_GEMINI_IMAGE_DIMENSION, MAX_GEMINI_IMAGE_DIMENSION),
                Image.Resampling.LANCZOS,
            )
            optimized = BytesIO()
            image.save(optimized, format="JPEG", quality=80, optimize=False)
            return optimized.getvalue(), "image/jpeg"
    except UnidentifiedImageError as exc:
        if Path(name).suffix.lower() in {".heic", ".heif"}:
            return data, mime_type
        raise ValueError(f"{name} could not be decoded as an image.") from exc
    except (OSError, Image.DecompressionBombError) as exc:
        if Path(name).suffix.lower() in {".heic", ".heif"}:
            return data, mime_type
        raise ValueError(f"{name} could not be prepared for Gemini.") from exc


def validate_image(path: Path) -> str:
    mime_type = IMAGE_MIME_TYPES.get(path.suffix.lower())
    if mime_type is None:
        raise ValueError(f"{path.name} is not a supported image format.")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not read {path.name}: {exc}") from exc
    if size > MAX_IMAGE_SIZE_BYTES:
        raise ValueError(f"{path.name} is larger than the 10 MB per-image limit.")
    if size == 0:
        raise ValueError(f"{path.name} is empty.")
    return mime_type


def load_preferences(path: Path = PREFERENCES_FILE) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "language": "English",
        "theme": "Auto",
        "voice_output": False,
    }
    if not path.exists():
        return defaults
    try:
        preferences = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load preferences: {exc}") from exc
    if not isinstance(preferences, dict):
        raise ValueError("Saved preferences must be an object.")
    language = preferences.get("language", defaults["language"])
    theme = preferences.get("theme", defaults["theme"])
    voice_output = preferences.get("voice_output", defaults["voice_output"])
    if language not in {"English", *SUPPORTED_LANGUAGES}:
        raise ValueError("Saved preferences contain an unsupported language.")
    if theme not in {"Auto", "Dark", "Light"}:
        raise ValueError("Saved preferences contain an unsupported theme.")
    if not isinstance(voice_output, bool):
        raise ValueError("Saved voice-output preference must be a boolean.")
    return {
        "language": language,
        "theme": theme,
        "voice_output": voice_output,
    }


def save_preferences(
    preferences: dict[str, Any],
    path: Path = PREFERENCES_FILE,
) -> None:
    if (
        preferences.get("language") not in {"English", *SUPPORTED_LANGUAGES}
        or preferences.get("theme") not in {"Auto", "Dark", "Light"}
        or not isinstance(preferences.get("voice_output"), bool)
    ):
        raise ValueError("Preferences contain an unsupported setting.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(preferences, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise ValueError(f"Could not save preferences: {exc}") from exc


def scheduled_theme(hour: int) -> str:
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        raise ValueError("Hour must be an integer from 0 to 23.")
    if hour >= THEME_SCHEDULE["dark_start_hour"] or hour < THEME_SCHEDULE["light_start_hour"]:
        return "dark"
    return "light"


def translate_text(text: str, language: str) -> str:
    if language == "English":
        return text
    translated = UI_TRANSLATIONS.get(language, {}).get(text)
    if translated is not None:
        return translated
    if text.startswith("●  "):
        return f"●  {translate_text(text[3:], language)}"
    if text.endswith(" apps selected"):
        count = text.removesuffix(" apps selected")
        if count.isdecimal():
            return (
                f"{count} application(s) sélectionnée(s)"
                if language == "Français"
                else f"تم اختيار {count} تطبيقات"
            )
    if ": " in text and text.split(": ", 1)[0].endswith(" image(s)"):
        count, names = text.split(": ", 1)
        count = count.removesuffix(" image(s)")
        if count.isdecimal():
            return (
                f"{count} image(s) : {names}"
                if language == "Français"
                else f"{count} صورة: {names}"
            )
    return text


def speech_language(language: str) -> str:
    try:
        return SUPPORTED_LANGUAGES[language]
    except KeyError as exc:
        raise ValueError(f"Unsupported speech language: {language}") from exc


def save_clipboard_image(
    image: Any,
    cache_dir: Path,
    preserve_paths: set[Path] | None = None,
) -> Path:
    width, height = image.size
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or width * height > MAX_CLIPBOARD_IMAGE_PIXELS
    ):
        raise ValueError("The clipboard image dimensions are too large.")
    preserved = {item.resolve() for item in (preserve_paths or set())}
    if len(preserved) >= MAX_CLIPBOARD_CACHE_FILES:
        raise ValueError("The clipboard image cache cannot preserve more selected images.")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"clipboard-{time.time_ns()}.png"
        image.save(path, format="PNG")
        validate_image(path)
        cached_images = sorted(
            cache_dir.glob("clipboard-*.png"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        removable = [item for item in cached_images if item.resolve() not in preserved]
        for stale_path in removable[MAX_CLIPBOARD_CACHE_FILES - len(preserved):]:
            stale_path.unlink()
        return path
    except (OSError, ValueError) as exc:
        if "path" in locals():
            path.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"Could not save clipboard image: {exc}") from exc


def load_shortcuts(path: Path = SHORTCUTS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return [
            {
                "name": item["name"],
                "targets": list(item["targets"]),
                "max_open": len(item["targets"]),
            }
            for item in DEFAULT_SHORTCUTS
        ]
    try:
        shortcuts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load saved shortcuts: {exc}") from exc
    if not isinstance(shortcuts, list):
        raise ValueError("Saved shortcuts must be a list.")
    for shortcut in shortcuts:
        if (
            not isinstance(shortcut, dict)
            or not isinstance(shortcut.get("name"), str)
            or not shortcut["name"].strip()
            or not isinstance(shortcut.get("targets"), list)
            or not shortcut["targets"]
            or not all(isinstance(target, str) and target.strip() for target in shortcut["targets"])
        ):
            raise ValueError("A saved shortcut has an invalid name or target list.")
        if len(shortcut["targets"]) > MAX_SHORTCUT_TARGETS:
            raise ValueError("A saved shortcut contains too many targets.")
        max_open = shortcut.setdefault("max_open", len(shortcut["targets"]))
        if (
            not isinstance(max_open, int)
            or isinstance(max_open, bool)
            or not 1 <= max_open <= MAX_SHORTCUT_TARGETS
            or max_open > len(shortcut["targets"])
        ):
            raise ValueError("A saved shortcut has an invalid maximum app count.")
    return shortcuts


def discover_installed_apps(
    appdata: str | None = None,
    program_data: str | None = None,
) -> list[dict[str, str]]:
    appdata = appdata or os.getenv("APPDATA")
    program_data = program_data or os.getenv("ProgramData")
    roots = [
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if appdata
        else None,
        Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if program_data
        else None,
    ]
    apps: dict[str, dict[str, str]] = {}
    for root in roots:
        if root is None or not root.is_dir():
            continue
        try:
            shortcuts = root.rglob("*.lnk")
            for shortcut in shortcuts:
                try:
                    if not shortcut.is_file():
                        continue
                except OSError:
                    continue
                name = shortcut.stem.strip()
                if not name or name.startswith("."):
                    continue
                apps.setdefault(
                    name.casefold(),
                    {
                        "name": name,
                        "target": f"startmenu:{shortcut.resolve()}",
                    },
                )
        except OSError:
            continue
    return sorted(apps.values(), key=lambda app: app["name"].casefold())


def shortcut_targets_to_open(targets: list[str], max_open: int) -> list[str]:
    if not isinstance(max_open, int) or isinstance(max_open, bool):
        raise ValueError("The maximum app count must be an integer.")
    if not 1 <= max_open <= min(MAX_SHORTCUT_TARGETS, len(targets)):
        raise ValueError("The maximum app count must be within the shortcut size.")
    return targets[:max_open]


def describe_gemini_error(error: Exception, language: str = "English") -> str:
    status_code = getattr(error, "status_code", None)
    error_name = type(error).__name__.casefold()
    safe_details = str(error).casefold()
    if status_code in {401, 403} or any(
        phrase in safe_details for phrase in ("invalid api key", "unauthorized", "authentication")
    ):
        message = "Gemini rejected the API key. Check your local .env value and key permissions."
        return translate_text(message, language)
    if status_code == 429 or any(
        phrase in safe_details for phrase in ("quota", "resource_exhausted", "rate limit")
    ):
        message = "Gemini is rate-limiting this key or its quota is exhausted. Check Google AI Studio."
        return translate_text(message, language)
    if any(
        phrase in error_name
        for phrase in ("timeout", "connect", "network", "transport")
    ):
        message = "Could not reach Gemini. Check your internet connection and try again."
        return translate_text(message, language)
    message = (
        f"Gemini test failed ({type(error).__name__}). "
        "Check the API key, model access, and internet connection."
    )
    return translate_text(message, language)


def save_shortcuts(shortcuts: list[dict[str, Any]], path: Path = SHORTCUTS_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(shortcuts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        raise ValueError(f"Could not save shortcuts: {exc}") from exc


def is_windows_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def set_windows_startup_enabled(
    enabled: bool,
    script_path: Path,
    python_executable: Path | None = None,
) -> None:
    if sys.platform != "win32":
        raise OSError("Starting with Windows is only available on Windows.")
    import winreg

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY)
    with key:
        if not enabled:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass
            return

        command = build_startup_command(script_path, python_executable)
        winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, command)


def build_startup_command(
    script_path: Path,
    python_executable: Path | None = None,
) -> str:
    executable = python_executable or Path(sys.executable)
    windowless_executable = executable.with_name("pythonw.exe")
    if windowless_executable.is_file():
        executable = windowless_executable
    return subprocess.list2cmdline(
        [str(executable), str(script_path.resolve()), "--startup"]
    )
