from __future__ import annotations

import base64
import binascii
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app_features import (
    MAX_IMAGE_ATTACHMENTS,
    MAX_IMAGE_REQUEST_SIZE_BYTES,
    MAX_IMAGE_SIZE_BYTES,
    build_user_content_from_bytes,
    describe_gemini_error,
    prepare_image_bytes,
)
from credits import (
    MIN_MESSAGE_CREDITS,
    CreditsExhausted,
    DailyCreditStore,
    calculate_message_credits,
)


MODEL_NAME = "gemini-3.5-flash-lite"
SYSTEM_PROMPT = (
    "You are AI Help You, a friendly and thoughtful desktop companion. "
    "Respond naturally and warmly in the language the user uses, including "
    "Tunisian Arabic, Arabic, or English. Be clear, useful, and honest. "
    "Answer directly and keep replies concise, usually 1-3 sentences, unless "
    "the user asks for more detail. "
    "When the user attaches an image or screenshot, inspect it and answer "
    "questions about its visible contents. "
    "Never claim to have performed a computer action unless the app confirms it."
)
API_PREFIX = "/api"
MAX_HISTORY_TURNS = 40
MAX_MESSAGE_LENGTH = 20_000
MAX_HISTORY_TEXT_LENGTH = 10_000
MAX_ENCODED_IMAGE_SIZE = 4 * ((MAX_IMAGE_SIZE_BYTES + 2) // 3)
MAX_ENCODED_REQUEST_SIZE = 4 * ((MAX_IMAGE_REQUEST_SIZE_BYTES + 2) // 3)

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"), override=False)


class BackendStartupError(RuntimeError):
    pass


class BackendRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ImageAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=40)
    data: str = Field(min_length=1, max_length=MAX_ENCODED_IMAGE_SIZE)


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "model"]
    text: str = Field(max_length=MAX_HISTORY_TEXT_LENGTH)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    images: list[ImageAttachment] = Field(default_factory=list, max_length=MAX_IMAGE_ATTACHMENTS)
    language: str = Field(default="English", max_length=20)


class ApiTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(default="English", max_length=20)


def _decode_images(images: list[ImageAttachment]) -> list[tuple[str, bytes, str]]:
    decoded_images: list[tuple[str, bytes, str]] = []
    total_encoded_size = 0
    for image in images:
        total_encoded_size += len(image.data)
        if total_encoded_size > MAX_ENCODED_REQUEST_SIZE:
            raise ValueError("Selected images exceed the 20 MB encoded request limit.")
        try:
            data = base64.b64decode(image.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"{image.name} is not valid base64 image data.") from exc
        if not data:
            raise ValueError(f"{image.name} is empty.")
        if len(data) > MAX_IMAGE_SIZE_BYTES:
            raise ValueError(f"{image.name} is larger than the 10 MB per-image limit.")
        decoded_images.append((image.name, data, image.mime_type))
    return decoded_images


def create_backend_app(
    app_token: str,
    client_factory: Callable[[str], Any] | None = None,
    api_key_provider: Callable[[], str | None] | None = None,
    credit_store: DailyCreditStore | None = None,
) -> FastAPI:
    app = FastAPI(title="AI Help You Local Backend", docs_url=None, redoc_url=None)
    app.state.gemini_client = None
    app.state.credit_store = credit_store or DailyCreditStore()

    def get_api_key() -> str | None:
        if api_key_provider is not None:
            return api_key_provider()
        return os.getenv("GEMINI_API_KEY", "").strip() or None

    def get_client() -> Any:
        api_key = get_api_key()
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini API key not found. Add GEMINI_API_KEY to the local .env file.",
            )
        if app.state.gemini_client is None:
            if client_factory is not None:
                app.state.gemini_client = client_factory(api_key)
            else:
                try:
                    from google import genai
                except ImportError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Gemini SDK is unavailable. Install the project requirements.",
                    ) from exc
                app.state.gemini_client = genai.Client(api_key=api_key)
        return app.state.gemini_client

    def authorize(x_app_token: str | None) -> None:
        if not x_app_token or not secrets.compare_digest(x_app_token, app_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This local backend request is not authorized.",
            )

    @app.get(f"{API_PREFIX}/health")
    def health(x_app_token: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(x_app_token)
        return {
            "status": "ok",
            "model": MODEL_NAME,
            "gemini_configured": bool(get_api_key()),
        }

    @app.get(f"{API_PREFIX}/credits")
    def credits(x_app_token: str | None = Header(default=None)) -> dict[str, int | str]:
        authorize(x_app_token)
        return app.state.credit_store.get_balance().as_dict()

    @app.post(f"{API_PREFIX}/gemini/test")
    def test_gemini(
        request: ApiTestRequest,
        x_app_token: str | None = Header(default=None),
    ) -> dict[str, str]:
        authorize(x_app_token)
        try:
            client = get_client()
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents="Reply with OK only.",
                config=_generation_config(max_output_tokens=128),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=describe_gemini_error(exc, request.language),
            ) from exc
        if not response.text:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned an empty response.",
            )
        return {"model": MODEL_NAME, "reply": response.text}

    @app.post(f"{API_PREFIX}/gemini/chat")
    def chat(
        request: ChatRequest,
        x_app_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        authorize(x_app_token)
        try:
            from google.genai import types
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini SDK is unavailable. Install the project requirements.",
            ) from exc
        try:
            images = _decode_images(request.images)
            current_message = build_user_content_from_bytes(
                request.message,
                images,
                types,
                optimize_images=False,
            )
            history = [
                types.Content(
                    role=turn.role,
                    parts=[types.Part.from_text(text=turn.text)],
                )
                for turn in request.history
            ]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        message_cost = calculate_message_credits(request.message, len(images))
        try:
            charged_balance = app.state.credit_store.charge(message_cost)
        except CreditsExhausted as exc:
            locked = exc.balance.credits < MIN_MESSAGE_CREDITS
            message = (
                "Locked — your daily credits are used up. Wait until 00:00."
                if locked
                else (
                    f"This message needs {message_cost} credits, but only "
                    f"{exc.balance.credits} remain. Shorten it or remove images."
                )
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": message,
                    "locked": locked,
                    **exc.balance.as_dict(),
                },
            ) from exc

        try:
            response = get_client().models.generate_content(
                model=MODEL_NAME,
                contents=[*history, current_message],
                config=_generation_config(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.5,
                    max_output_tokens=192,
                ),
            )
        except HTTPException:
            app.state.credit_store.refund(message_cost, charged_balance.credit_date)
            raise
        except Exception as exc:
            app.state.credit_store.refund(message_cost, charged_balance.credit_date)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=describe_gemini_error(exc, request.language),
            ) from exc
        if not response.text:
            app.state.credit_store.refund(message_cost, charged_balance.credit_date)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gemini returned an empty response. Your credits were restored.",
            )
        return {
            "model": MODEL_NAME,
            "reply": response.text,
            "credits_used": message_cost,
            **app.state.credit_store.get_balance().as_dict(),
        }

    return app


def _generation_config(**kwargs: Any) -> Any:
    try:
        from google.genai import types
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini SDK is unavailable. Install the project requirements.",
        ) from exc
    return types.GenerateContentConfig(**kwargs)


class LocalBackend:
    def __init__(self, startup_timeout: float = 5.0) -> None:
        try:
            import uvicorn
        except ImportError as exc:
            raise BackendStartupError(
                "FastAPI backend dependencies are missing. Install requirements.txt."
            ) from exc

        self._token = secrets.token_urlsafe(32)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._base_url = ""
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket = server_socket
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", 0))
            server_socket.listen(128)
            port = server_socket.getsockname()[1]
            config = uvicorn.Config(
                create_backend_app(self._token),
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [server_socket]},
                name="ai-help-you-backend",
                daemon=True,
            )
            self._thread.start()
            self._base_url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                if self._server.started:
                    self.health()
                    return
                if not self._thread.is_alive():
                    raise BackendStartupError("The local AI backend stopped during startup.")
                time.sleep(0.05)
            raise BackendStartupError("The local AI backend did not start in time.")
        except Exception as exc:
            self.close()
            if isinstance(exc, BackendStartupError):
                raise
            raise BackendStartupError(f"Could not start the local AI backend: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def credits(self) -> dict[str, Any]:
        return self._request("GET", "/api/credits")

    def test_gemini(self, language: str) -> dict[str, str]:
        return self._request("POST", "/api/gemini/test", {"language": language})

    def chat(
        self,
        message: str,
        history: list[dict[str, str]],
        image_paths: list[Path],
        language: str,
    ) -> dict[str, Any]:
        images = []
        for path in image_paths:
            from app_features import validate_image

            mime_type = validate_image(path)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise BackendRequestError(f"Could not read {path.name}: {exc}") from exc
            data, mime_type = prepare_image_bytes(path.name, data, mime_type)
            images.append(
                {
                    "name": path.name,
                    "mime_type": mime_type,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            )
        result = self._request(
            "POST",
            "/api/gemini/chat",
            {
                "message": message,
                "history": history,
                "images": images,
                "language": language,
            },
        )
        if not isinstance(result.get("reply"), str) or not result["reply"]:
            raise BackendRequestError("The local AI backend returned an empty response.")
        return result

    def close(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._server = None
        self._thread = None
        self._socket = None

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers={
                "X-App-Token": self._token,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = (
                    payload.get("detail", "The local AI backend request failed.")
                    if isinstance(payload, dict)
                    else "The local AI backend request failed."
                )
                message = (
                    detail.get("message", "The local AI backend request failed.")
                    if isinstance(detail, dict)
                    else detail
                )
            except (UnicodeError, ValueError, AttributeError):
                detail = None
                message = "The local AI backend request failed."
            raise BackendRequestError(str(message), exc.code, detail) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BackendRequestError(
                "Could not reach the local AI backend. Restart the app and try again."
            ) from exc
        except (UnicodeError, ValueError) as exc:
            raise BackendRequestError(
                "The local AI backend returned an invalid response."
            ) from exc
        if not isinstance(result, dict):
            raise BackendRequestError("The local AI backend returned an invalid response.")
        return result
