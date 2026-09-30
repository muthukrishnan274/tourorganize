import os
from typing import Any

from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import types

from chatbot_config import CHATBOT_TITLE, GEMINI_MODEL, SYSTEM_PROMPT

app = Flask(__name__)

MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_ITEM_LENGTH = 4000
MAX_HISTORY_TOTAL_CHARS = 24000


def _safe_error(message: str, status: int):
    return jsonify({"error": message}), status


def _validate_text(value: Any, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be empty.")
    if len(value) > max_length:
        raise ValueError(f"{field_name} is too long.")
    return value


def validate_history(history: Any) -> list[dict[str, str]]:
    if history is None:
        return []
    if not isinstance(history, list):
        raise ValueError("history must be an array.")
    if len(history) > MAX_HISTORY_MESSAGES:
        raise ValueError("conversation history is too long.")

    validated: list[dict[str, str]] = []
    total_chars = 0

    for index, item in enumerate(history):
        if not isinstance(item, dict):
            raise ValueError(f"history item {index + 1} is invalid.")

        role = item.get("role")
        content = item.get("content")

        if role not in {"user", "assistant"}:
            raise ValueError(f"history item {index + 1} has an invalid role.")

        content = _validate_text(
            content,
            f"history item {index + 1} content",
            MAX_HISTORY_ITEM_LENGTH,
        )
        total_chars += len(content)
        if total_chars > MAX_HISTORY_TOTAL_CHARS:
            raise ValueError("conversation history is too large.")

        validated.append({"role": role, "content": content})

    return validated


def build_contents(history: list[dict[str, str]], message: str) -> list[types.Content]:
    contents: list[types.Content] = []

    for item in history:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part(text=item["content"])],
            )
        )

    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=message)],
        )
    )
    return contents


@app.get("/")
def index():
    return render_template("index.html", chatbot_title=CHATBOT_TITLE)


@app.post("/api/chat")
def chat():
    if not request.is_json:
        return _safe_error("Request body must be JSON.", 400)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _safe_error("Invalid JSON request body.", 400)

    try:
        message = _validate_text(data.get("message"), "message", MAX_MESSAGE_LENGTH)
        history = validate_history(data.get("history", []))
    except ValueError as exc:
        return _safe_error(str(exc), 400)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _safe_error("The AI service is not configured on the server.", 503)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=build_contents(history, message),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.4,
                max_output_tokens=1200,
            ),
        )

        reply = (response.text or "").strip()
        if not reply:
            return _safe_error("The AI service returned an empty response.", 502)

        return jsonify({"reply": reply})

    except Exception:
        app.logger.exception("Gemini request failed")
        return _safe_error("The AI service could not complete the request. Please try again.", 502)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
