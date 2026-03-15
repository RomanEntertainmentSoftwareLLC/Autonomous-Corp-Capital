from __future__ import annotations

import json
import os
import urllib.request
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
        structured = prompt.get("structured_output", {})
        role_spec = prompt.get("role_spec", "")
        persona_description = prompt.get("persona_description", "")
        description = structured.get("description", "")
        required_keys = structured.get("required_keys", [])
        system_text = (
            f"{role_spec}\n{persona_description}\n{description}\n"
            f"Produce a valid JSON object with the following keys exactly: {required_keys}."
            "Stick to the persona and do not invent unauthorized actions."
        )
        user_text = json.dumps({"message": message, "prompt": prompt})
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
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
        except Exception:
            return SimpleLLMAdapter().reason(message, prompt)
        choice = data["choices"][0]["message"]["content"]
        try:
            result = json.loads(choice)
        except json.JSONDecodeError:
            return SimpleLLMAdapter().reason(message, prompt)
        return result


class SimpleLLMAdapter(LLMAdapter):
    def _format(self, template: str, prompt: Dict[str, Any]) -> str:
        try:
            return template.format(scope=prompt.get("scope", ""))
        except Exception:
            return template

    def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        lowered = message.lower()
        persona = prompt.get("persona", {})
        examples = persona.get("example_responses", {})
        role_type = prompt.get("role_type", "").lower()
        if role_type == "analyst":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            missing = insights.get("missing_data", [])
            analysis_summary = (
                f"{insights.get('metadata_summary', 'Unknown status')} with {queue_summary.get('new', 0)} new tasks."
            )
            evidence = []
            if insights.get("metadata_summary"):
                evidence.append(f"Lifecycle: {insights['metadata_summary']}")
            if insights.get("logs_present"):
                evidence.append("Results logs are present")
            if insights.get("config_summary"):
                symbols = insights["config_summary"].get("symbols")
                if symbols:
                    evidence.append(f"Symbols: {symbols}")
            missing_data = missing or ["metadata","config","logs"]
            suggested_followup = (
                "Check for missing logs and refresh the leaderboard before Manager acts."
                if missing else "None—data looks complete."
            )
            reply_template = (
                examples.get("summary", ["Here are the current analytics."])[0]
                if examples.get("summary")
                else "Here are the current analytics."
            )
            reply = self._format(reply_template, prompt)
            if any(greet in lowered for greet in ("hi", "hello", "glorious", "how are")):
                reply_template = examples.get("greeting", [reply])[0]
                reply = self._format(reply_template, prompt)
                return {
                    "reply_text": reply,
                    "analysis_summary": reply,
                    "evidence": evidence,
                    "missing_data": missing_data,
                    "suggested_followup": suggested_followup,
                    "escalation": False,
                    "queue_action": "none",
                    "task_type": "analysis",
                    "priority": "low",
                }
            return {
                "reply_text": reply,
                "analysis_summary": analysis_summary,
                "evidence": evidence,
                "missing_data": missing_data,
                "suggested_followup": suggested_followup,
                "escalation": False,
                "queue_action": "none",
                "task_type": "analysis",
                "priority": "medium",
            }
        if any(greet in lowered for greet in ("hi", "hello", "glorious", "how are")):
            reply_template = examples.get("greeting", ["I’m tuned into the queue—what would you like routed?"])[0]
            reply = self._format(reply_template, prompt)
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
        return {
            "reply_text": f"Routing to {recipient} for {task_type} (priority {priority}).",
            "task_type": task_type,
            "priority": priority,
            "recipient": recipient,
            "requested_action": action,
            "queue_action": "create",
            "escalate": priority == "emergency",
        }
