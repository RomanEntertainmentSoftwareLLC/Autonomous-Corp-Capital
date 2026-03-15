from __future__ import annotations

import json
import os
import urllib.request
from urllib.error import HTTPError, URLError
from abc import ABC, abstractmethod
from typing import Any, Dict


class LLMAdapter(ABC):
    @abstractmethod
    def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        pass


class OpenAIAdapter(LLMAdapter):
    def __init__(self) -> None:
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._api_key = os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise EnvironmentError("OPENAI_API_KEY environment variable is not set")
        self._endpoint = "https://api.openai.com/v1/chat/completions"

    def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are Pam, the organizational coordinator. "
                        "Return a JSON object with keys reply_text, task_type, priority, recipient, requested_action, queue_action, escalate. "
                        "Follow policy: no capital allocations, no risk overrides, no final strategy decisions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({
                        "message": message,
                        "prompt": prompt,
                    }),
                },
            ],
            "temperature": 0.3,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode())
        except (HTTPError, URLError, TimeoutError):
            return SimpleLLMAdapter().reason(message, prompt)
        choice = data["choices"][0]["message"]["content"]
        try:
            result = json.loads(choice)
        except json.JSONDecodeError:
            raise ValueError("OpenAI response did not contain valid JSON")
        return result


class SimpleLLMAdapter(LLMAdapter):
    def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        lowered = message.lower()
        persona = prompt.get("persona", {})
        examples = persona.get("example_responses", {})
        if any(greet in lowered for greet in ("hi", "hello", "glorious", "how are")):
            reply = examples.get("greeting", ["I’m tuned into the queue—what would you like routed?"])[0]
            return {
                "reply_text": reply,
                "task_type": "greeting",
                "priority": "low",
                "recipient": "Analyst",
                "requested_action": "Hold for next actionable request",
                "queue_action": "none",
                "escalate": False,
            }
        priority = prompt.get("priority", "medium")
        task_type = "general_triage"
        recipient = "Analyst"
        for keyword, tt, rcpt in prompt.get("task_rules", []):
            if keyword in lowered:
                task_type, recipient = tt, rcpt
                break
        action = f"{recipient}: handle {task_type} for {prompt['scope']}"
        reply_options = examples.get("followup", [f"Routing to {recipient} for {task_type} (priority {priority})."])
        reply = reply_options[0]
        return {
            "reply_text": reply,
            "task_type": task_type,
            "priority": priority,
            "recipient": recipient,
            "requested_action": action,
            "queue_action": "create",
            "escalate": priority == "emergency",
        }
