from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


class DesktopActionError(RuntimeError):
    """A local desktop action could not be completed."""


@dataclass(frozen=True)
class PlannedMove:
    source: Path
    destination: Path


_CATEGORY_EXTENSIONS = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "Applications": {".exe", ".msi", ".lnk", ".app"},
}
_PROGRAMS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
}
_PROGRAM_ALIASES = {
    "code": "code.exe",
    "vscode": "code.exe",
    "visual studio code": "code.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
}


def get_desktop_path() -> Path:
    return Path(os.path.expanduser("~/Desktop"))


def _category_for(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, extensions in _CATEGORY_EXTENSIONS.items():
        if suffix in extensions:
            return category
    return "Other"


def _available_destination(folder: Path, name: str, reserved: set[Path]) -> Path:
    destination = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 1
    while destination.exists() or destination in reserved:
        destination = folder / f"{stem} ({index}){suffix}"
        index += 1
    return destination


def organize_preview(desktop: Path) -> list[PlannedMove]:
    if not desktop.exists():
        raise DesktopActionError(f"Desktop folder does not exist: {desktop}")
    if not desktop.is_dir():
        raise DesktopActionError(f"Desktop path is not a folder: {desktop}")

    try:
        entries = sorted(desktop.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        raise DesktopActionError(f"Could not read the desktop folder: {exc}") from exc

    planned: list[PlannedMove] = []
    reserved: set[Path] = set()
    for entry in entries:
        if entry.name.startswith(".") or not entry.is_file():
            continue
        folder = desktop / _category_for(entry)
        destination = _available_destination(folder, entry.name, reserved)
        planned.append(PlannedMove(entry, destination))
        reserved.add(destination)
    return planned


def clean_desktop(moves: list[PlannedMove]) -> list[PlannedMove]:
    completed: list[PlannedMove] = []
    for move in moves:
        try:
            move.destination.parent.mkdir(parents=True, exist_ok=True)
            if move.destination.exists():
                raise FileExistsError(f"Destination already exists: {move.destination}")
            shutil.move(str(move.source), str(move.destination))
            completed.append(move)
        except OSError as exc:
            details = ", ".join(
                f"{item.source.name} → {item.destination.parent.name}"
                for item in completed
            )
            completed_note = f" Already moved: {details}." if details else ""
            raise DesktopActionError(
                f"Could not move {move.source.name}: {exc}.{completed_note}"
            ) from exc
    return completed


def take_screenshot(desktop: Path) -> Path:
    try:
        import pyautogui
    except ImportError as exc:
        raise DesktopActionError(
            "pyautogui is not installed, so screenshots are unavailable."
        ) from exc

    filename = f"AI-Tool-Pro-Max-{datetime.now():%Y%m%d-%H%M%S}.png"
    destination = desktop / filename
    counter = 1
    while destination.exists():
        destination = desktop / f"AI-Tool-Pro-Max-{datetime.now():%Y%m%d-%H%M%S}-{counter}.png"
        counter += 1
    try:
        pyautogui.screenshot().save(destination)
    except Exception as exc:
        raise DesktopActionError(f"Could not capture the screen: {exc}") from exc
    return destination


def launch_program(program: str) -> None:
    normalized = program.strip().lower()
    executable = _PROGRAMS.get(normalized) or _PROGRAM_ALIASES.get(normalized)
    if executable is None:
        raise DesktopActionError(f"Unsupported program: {program}")

    resolved = shutil.which(executable)
    if resolved is None and normalized in {"code", "vscode", "visual studio code"}:
        candidates = [
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.getenv("ProgramFiles", "C:\\Program Files")) / "Microsoft VS Code" / "Code.exe",
        ]
        resolved = next((str(path) for path in candidates if path.is_file()), None)
    elif resolved is None and normalized in {"chrome", "google chrome"}:
        candidates = [
            Path(os.getenv("ProgramFiles", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.getenv("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        resolved = next((str(path) for path in candidates if path.is_file()), None)
    executable = resolved or executable
    try:
        subprocess.Popen([executable], shell=False)
    except OSError as exc:
        raise DesktopActionError(f"Could not launch {program}: {exc}") from exc


def launch_target(target: str) -> None:
    validate_shortcut_target(target)
    target = target.strip()

    if target.lower().startswith("startmenu:"):
        shortcut = Path(target[len("startmenu:"):])
        try:
            os.startfile(str(shortcut))
        except (AttributeError, OSError) as exc:
            raise DesktopActionError(
                f"Could not open Start menu app '{shortcut.stem}': {exc}"
            ) from exc
        return

    parsed = urlparse(target)
    if parsed.scheme:
        if not webbrowser.open(target, new=2):
            raise DesktopActionError(f"Could not open website: {target}")
        return

    normalized = target.lower()
    if normalized in {"browser", "web browser"}:
        if not webbrowser.open("https://www.google.com", new=2):
            raise DesktopActionError("Could not open your default browser.")
        return

    aliases = {
        "calculator": "calculator",
        "chrome": "chrome",
        "code": "code",
        "edge": "edge",
        "explorer": "explorer",
        "firefox": "firefox",
        "google chrome": "chrome",
        "notepad": "notepad",
        "msedge": "edge",
        "visual studio code": "code",
        "vscode": "code",
    }
    if normalized in aliases:
        launch_program(aliases[normalized])
        return

    executable_path = Path(target).expanduser()
    if not executable_path.is_absolute() or executable_path.suffix.lower() != ".exe":
        raise DesktopActionError(
            f"Unsupported shortcut target: {target}. Use a website, a supported app name, or select an .exe file."
        )
    if not executable_path.is_file():
        raise DesktopActionError(f"Application was not found: {executable_path}")
    try:
        subprocess.Popen([str(executable_path)], shell=False)
    except OSError as exc:
        raise DesktopActionError(f"Could not launch {target}: {exc}") from exc


def validate_shortcut_target(target: str) -> None:
    target = target.strip()
    if not target:
        raise DesktopActionError("Shortcut target cannot be empty.")

    if target.lower().startswith("startmenu:"):
        shortcut = Path(target[len("startmenu:"):])
        if shortcut.is_absolute() and shortcut.suffix.lower() == ".lnk" and shortcut.is_file():
            return
        raise DesktopActionError(
            f"Start menu app shortcut was not found: {shortcut}"
        )

    parsed = urlparse(target)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DesktopActionError(
                "Website shortcuts must use a valid http:// or https:// URL."
            )
        return

    aliases = {
        "browser",
        "web browser",
        "calculator",
        "chrome",
        "code",
        "edge",
        "explorer",
        "firefox",
        "google chrome",
        "msedge",
        "notepad",
        "visual studio code",
        "vscode",
    }
    if target.lower() in aliases:
        return

    executable_path = Path(target).expanduser()
    if (
        executable_path.is_absolute()
        and executable_path.suffix.lower() == ".exe"
        and executable_path.is_file()
    ):
        return
    raise DesktopActionError(
        f"Unsupported shortcut target: {target}. Use a website, a supported app name, or select an .exe file."
    )
