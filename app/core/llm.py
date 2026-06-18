from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request
from typing import Any

from app.config import AppConfig


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, config: AppConfig) -> None:
        self.api_key = config.openai_api_key
        self.model = config.openai_model
        self.base_url = config.openai_base_url.rstrip("/")
        self.temperature = config.temperature

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # 这里使用 OpenAI 兼容的 Chat Completions 协议，而不是绑定某个 SDK。
        # 好处是后续可以较容易切换到 Azure OpenAI、DeepSeek、Qwen 等兼容接口。
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not configured.")
        if not self.model:
            raise LLMError("OPENAI_MODEL is not configured.")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            # tools 是从 ToolRegistry 导出的 function schema。
            # tool_choice=auto 表示让模型自己判断是否需要调用工具。
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # API Key 只放在请求头里，不写日志、不打印，避免泄露。
        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"LLM network error: {exc.reason}") from exc
        except http.client.RemoteDisconnected as exc:
            raise LLMError("LLM network error: remote end closed connection without response.") from exc
        except socket.timeout as exc:
            raise LLMError("LLM network error: request timed out.") from exc
        except json.JSONDecodeError as exc:
            raise LLMError("LLM response is not valid JSON.") from exc

        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response: {data}") from exc
