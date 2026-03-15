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
            return template.format(scope=prompt.get("target_scope", prompt.get("scope", "")))
        except Exception:
            return template

    def reason(self, message: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        lowered = message.lower()
        persona = prompt.get("persona", {})
        examples = persona.get("example_responses", {})
        role_type = prompt.get("role_type", "").lower()
        target_scope = prompt.get("target_scope", prompt.get("scope", ""))

        if role_type == "analyst":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            missing = insights.get("missing_data", [])
            lifecycle = insights.get("metadata_summary", "unknown")
            new_tasks = queue_summary.get("new", 0)
            analysis_summary = f"{target_scope} lifecycle is {lifecycle} with {new_tasks} new task(s)."
            evidence = []
            if lifecycle:
                evidence.append(f"Lifecycle: {lifecycle}")
            if insights.get("leaderboard_summary"):
                evidence.append("Leaderboard data available")
            if insights.get("logs_present"):
                evidence.append("Results logs are present")
            if insights.get("manager_action"):
                recommendation = insights["manager_action"].get("recommendation")
                if recommendation:
                    evidence.append(f"Manager recommendation: {recommendation}")
            missing_data = missing or ["metadata", "config", "leaderboard", "logs"]
            suggested_followup = (
                "Check for missing logs and refresh the leaderboard before Manager acts."
                if missing else "Data looks sufficiently complete for now."
            )
            reply_template = examples.get("summary", ["Here are the current analytics for {scope}."])[0]
            reply = self._format(reply_template, prompt)
            if any(greet in lowered for greet in ("hi", "hello", "glorious", "how are")):
                reply_template = examples.get("greeting", [reply])[0]
                reply = self._format(reply_template, prompt)
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

        if role_type == "manager":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            missing = insights.get("missing_data", [])
            lifecycle = insights.get("metadata_summary", "unknown")
            new_tasks = queue_summary.get("new", 0)
            evidence = [f"Lifecycle: {lifecycle}"] if lifecycle else []
            if insights.get("leaderboard_summary"):
                evidence.append("Leaderboard data available")
            manager_action = insights.get("manager_action")
            if manager_action:
                recommendation = manager_action.get("recommendation") or "Hold"
                reason = manager_action.get("reason")
                if recommendation:
                    evidence.append(f"Manager recommendation: {recommendation}")
            else:
                recommendation = "Hold"
                reason = "Awaiting clearer evidence before proposing action."
            rationale = f"{lifecycle} lifecycle with {new_tasks} new queue item(s)."
            missing_data = missing or ["metadata", "config", "leaderboard", "logs"]
            suggested_followup = (
                "Ask Bob for the latest logs or have Iris refresh the leaderboard before deciding."
                if missing else "Proceed to implement the recommended action."
            )
            reply_template = examples.get("recommendation", ["Based on the data, I suggest {recommendation}."])[0]
            reply = self._format(reply_template, prompt)
            reply = reply.replace("{recommendation}", recommendation)
            return {
                "reply_text": reply,
                "recommendation": recommendation,
                "rationale": rationale + (" Reason: " + reason + "." if reason else ""),
                "evidence": evidence,
                "missing_data": missing_data,
                "suggested_followup": suggested_followup,
                "escalation": False,
                "queue_action": "none",
                "task_type": "management",
                "priority": "medium",
            }

        if role_type == "researcher":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            missing = insights.get("missing_data", [])
            lifecycle = insights.get("metadata_summary", "unknown")
            new_tasks = queue_summary.get("new", 0)
            evidence = [f"Lifecycle: {lifecycle}"] if lifecycle else []
            if insights.get("leaderboard_summary"):
                evidence.append("Leaderboard data available")
            if insights.get("manager_action"):
                recommendation = insights["manager_action"].get("recommendation")
                if recommendation:
                    evidence.append(f"Manager recommendation: {recommendation}")
            missing_data = missing or ["metadata", "config", "leaderboard", "logs"]
            suggested_followup = (
                "Design a focused backtest or data sweep to resolve the missing pieces."
                if missing else "Explore a controlled experiment based on current insights."
            )
            research_summary = f"{target_scope} shows {lifecycle} status with {new_tasks} open tickets."
            ideas = ["Test the current strategy variation with tighter stop rules."]
            hypotheses = ["The mixed EMA/RSI approach may underperform in volatile regimes."]
            reply_template = examples.get("recommendation", ["Based on the data, I suggest exploring {recommendation}."])[0]
            reply = self._format(reply_template, prompt)
            reply = reply.replace("{recommendation}", ideas[0])
            return {
                "reply_text": reply,
                "research_summary": research_summary,
                "ideas": ideas,
                "hypotheses": hypotheses,
                "evidence": evidence,
                "missing_data": missing_data,
                "suggested_followup": suggested_followup,
                "escalation": False,
                "queue_action": "none",
                "task_type": "research",
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
