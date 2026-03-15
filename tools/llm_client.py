from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List


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
        agent_scope = prompt.get("agent_scope", prompt.get("scope", ""))

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
            missing_text = ", ".join(missing_data)
            suggested_followup = (
                "Check for missing logs and refresh the leaderboard before Manager acts."
                if missing else "Data looks sufficiently complete for now."
            )
            evidence_text = "; ".join(evidence) or "no strong evidence yet"
            reply = (
                f"Iris@{agent_scope} reports on {target_scope}: {analysis_summary} "
                f"Evidence: {evidence_text}. Missing: {missing_text}."
            )
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
            missing_text = ", ".join(missing_data)
            suggested_followup = (
                "Ask Bob for the latest logs or have Iris refresh the leaderboard before deciding."
                if missing else "Proceed to implement the recommended action."
            )
            evidence_text = "; ".join(evidence) or "no clear evidence yet"
            reply = (
                f"Vera@{agent_scope} recommends {recommendation}. Rationale: {rationale}. "
                f"Evidence: {evidence_text}. Missing: {missing_text}."
            )
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
            missing_text = ", ".join(missing_data)
            suggested_followup = (
                "Design a focused backtest or data sweep to resolve the missing pieces."
                if missing else "Explore a controlled experiment based on current insights."
            )
            research_summary = f"{target_scope} shows {lifecycle} status with {new_tasks} open tickets."
            ideas = ["Test the current strategy variation with tighter stop rules."]
            hypotheses = ["The mixed EMA/RSI approach may underperform in volatile regimes."]
            evidence_text = "; ".join(evidence) or "no strong evidence yet"
            reply = (
                f"Rowan@{agent_scope} notes {research_summary} Idea: {ideas[0]}. "
                f"Evidence: {evidence_text}. Missing: {missing_text}."
            )
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
        if role_type == "cfo":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            allocation = insights.get("allocation", {})
            manager_action = insights.get("manager_action") or {}
            agent_reports = insights.get("agent_reports", {})
            vera_reports = agent_reports.get("Vera", [])
            latest_vera = vera_reports[-1] if vera_reports else {}
            lifecycle = insights.get("metadata_summary", "unknown")
            new_items = queue_summary.get("new", 0)
            missing = insights.get("missing_data", [])
            caution_level = "high" if new_items > 3 or missing else "moderate" if new_items else "low"
            spending_posture = "reduce" if caution_level == "high" else "preserve" if caution_level == "moderate" else "justify"
            recommendation = (
                "Hold new spending until runway clarity improves and missing data is resolved."
                if caution_level in ("high", "moderate")
                else "We can justify evidence-backed, limited spend while monitoring runway."
            )
            alloc_percent = allocation.get("percent")
            evidence = []
            if lifecycle:
                evidence.append(f"Lifecycle: {lifecycle}")
            if alloc_percent is not None:
                evidence.append(f"Allocation at {alloc_percent}% for {target_scope}")
            manager_reco = manager_action.get("recommendation")
            if manager_reco:
                evidence.append(f"Manager recommends {manager_reco}")
            vera_recommendation = latest_vera.get("recommendation")
            treasury = insights.get("treasury_snapshot", {})
            reserve = treasury.get("reserve_capital")
            allocatable = treasury.get("allocatable_capital")
            if reserve is not None:
                evidence.append(f"Reserve capital: {reserve}")
            if allocatable is not None:
                evidence.append(f"Allocatable capital: {allocatable}")
            missing_text = ", ".join(missing) if missing else "none"
            manager_context = vera_recommendation or manager_reco or "no fresh recommendation"
            health_parts = [f"{target_scope} lifecycle: {lifecycle}"]
            if alloc_percent is not None:
                health_parts.append(f"allocation: {alloc_percent}%")
            health_parts.append(f"{new_items} new queue item(s)")
            financial_health = "; ".join(health_parts)
            caution_text = f"Caution level: {caution_level}."
            if missing:
                caution_text += f" Missing data: {missing_text}."
            rationale_parts = [f"{target_scope} lifecycle: {lifecycle}", f"{new_items} new queue item(s)"]
            if alloc_percent is not None:
                rationale_parts.append(f"{alloc_percent}% allocation")
            if reserve is not None:
                rationale_parts.append(f"reserve {reserve}")
            if missing:
                rationale_parts.append(f"missing data: {missing_text}")
            financial_rationale = "; ".join(rationale_parts)
            treasurer_instruction = (
                "Prepare a justification for extra capital if the CEO wants further spend."
                if caution_level == "high"
                else "Preserve reserves and avoid new capital requests for now."
            )
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Queue has {new_items} new item(s); missing data: {missing_text}.",
                    "next_steps": "Hold new spend routing until CFO clears the runway.",
                },
                {
                    "recipient": "CEO",
                    "summary": f"{target_scope} is {lifecycle} with manager context: {manager_context}.",
                    "next_steps": "Delay aggressive experimentation until runway clarity returns.",
                },
                {
                    "recipient": "Master Treasurer",
                    "summary": f"Reserves {reserve if reserve is not None else 'unknown'} / allocatable {allocatable if allocatable is not None else 'unknown'}; caution {caution_level}.",
                    "next_steps": treasurer_instruction,
                },
            ]
            suggested_followup = (
                f"Revisit after resolving {missing_text}." if missing else "Monitor runway and revisit if new spend is proposed."
            )
            evidence_text = "; ".join(evidence) or "no strong evidence yet"
            reply = (
                f"Bianca@{agent_scope} sees {target_scope} cash posture {caution_text} {recommendation}"
                f" Evidence: {evidence_text}. Missing: {missing_text}."
            )
            return {
                "reply_text": reply,
                "task_type": "financial_review",
                "priority": "medium",
                "recipient": "Bianca",
                "requested_action": f"Bianca: handle financial_review for {target_scope}",
                "queue_action": "none",
                "escalation": False,
                "financial_health_summary": financial_health,
                "cash_runway_caution": caution_text,
                "spending_posture": spending_posture,
                "recommendation": recommendation,
                "financial_rationale": financial_rationale,
                "evidence": evidence,
                "missing_data": missing,
                "suggested_followup": suggested_followup,
                "packets": packets,
            }
        if role_type == "ceo":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            agent_reports = insights.get("agent_reports", {})
            def latest_report(name: str) -> dict:
                entries = agent_reports.get(name) or []
                return entries[-1] if entries else {}
            latest_iris = latest_report("Iris")
            latest_vera = latest_report("Vera")
            latest_rowan = latest_report("Rowan")
            latest_bianca = latest_report("Bianca")
            latest_pam = latest_report("Pam")
            manager_action = insights.get("manager_action") or {}
            manager_recommendation = manager_action.get("recommendation")
            lifecycle = insights.get("metadata_summary", "unknown")
            allocation = insights.get("allocation", {})
            allocation_percent = allocation.get("percent")
            missing = insights.get("missing_data", [])
            new_items = queue_summary.get("new", 0)
            bianca_posture = latest_bianca.get("spending_posture")
            iris_summary = latest_iris.get("analysis_summary")
            manager_context = latest_vera.get("recommendation") or manager_recommendation
            rowan_idea = (latest_rowan.get("ideas") or [None])[0]
            rowan_hypothesis = (latest_rowan.get("hypotheses") or [None])[0]
            missing_text = ", ".join(missing) if missing else "none"
            escalate_flag = bool(missing and new_items > 2)
            if escalate_flag:
                decision = "escalate"
                approval_decision = "escalate"
                action_directive = "Escalate to YamYam with the missing data and queue pressure before proceeding."
                request_more_evidence = f"Provide {missing_text} along with a YamYam-aligned risk brief."
            elif missing:
                decision = "hold"
                approval_decision = "request more evidence"
                action_directive = "Hold all company actions until the missing data is collected."
                request_more_evidence = f"Need {missing_text} and a refreshed readout before moving forward."
            elif bianca_posture == "reduce":
                decision = "hold"
                approval_decision = "defer"
                action_directive = "Preserve cash while Bianca recalibrates the runway."
                request_more_evidence = "Ask Bianca for a refreshed runway and Iris/Vera updates."
            else:
                decision = "proceed"
                approval_decision = "approve"
                if manager_context and manager_context.upper() in ("CLONE", "GROW", "PROMOTE"):
                    action_directive = f"Approve Vera's {manager_context.lower()} recommendation with Bianca watching the runway."
                else:
                    action_directive = "Move forward with the execution while keeping a close eye on finance and the queue."
                request_more_evidence = "Keep me posted if the queue or treasury shifts."
            summary_parts = []
            if iris_summary:
                summary_parts.append(f"Iris: {iris_summary}")
            if manager_context:
                summary_parts.append(f"Vera: {manager_context}")
            if rowan_idea:
                summary_parts.append(f"Rowan idea: {rowan_idea}")
            if bianca_posture:
                summary_parts.append(f"Bianca posture: {bianca_posture}")
            if latest_pam.get("summary"):
                summary_parts.append(f"Pam: {latest_pam.get('summary')}")
            executive_summary = summary_parts and " | ".join(summary_parts) or f"{target_scope} is {lifecycle}."
            rationale_components = [f"{target_scope} lifecycle: {lifecycle}"]
            if allocation_percent is not None:
                rationale_components.append(f"Allocation {allocation_percent}%")
            if manager_context:
                rationale_components.append(f"Manager recommends {manager_context}")
            if missing:
                rationale_components.append(f"Missing data: {missing_text}")
            rationale = "; ".join(rationale_components)
            evidence = rationale_components.copy()
            suggested_followup = request_more_evidence if missing else "Execute the directive and loop me in if anything shifts."
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Queue has {new_items} new item(s); missing: {missing_text}.",
                    "next_steps": action_directive,
                },
                {
                    "recipient": "Vera",
                    "summary": manager_context or "No fresh recommendation",
                    "next_steps": "Align any proposals with the CEO decision.",
                },
                {
                    "recipient": "Bianca",
                    "summary": f"Spending posture: {bianca_posture or 'unknown'}; allocation {allocation_percent if allocation_percent is not None else 'unknown'}%",
                    "next_steps": "Keep runway updates flowing.",
                },
                {
                    "recipient": "Rowan",
                    "summary": f"Research idea: {rowan_idea or 'none'}; hypothesis: {rowan_hypothesis or 'none'}",
                    "next_steps": "Adjust experiments per the CEO directive.",
                },
            ]
            if escalate_flag:
                packets.append({
                    "recipient": "YamYam",
                    "summary": f"Escalating due to {missing_text} while {new_items} queue item(s) wait.",
                    "next_steps": "Advise on risk/treasury limits.",
                })
            return {
                "reply_text": f"Lucian@{agent_scope} decision for {target_scope}: {decision}. {action_directive}",
                "task_type": "executive_decision",
                "priority": "high" if escalate_flag else "medium",
                "recipient": "Lucian",
                "requested_action": f"Lucian: handle executive_decision for {target_scope}",
                "queue_action": "none",
                "escalation": escalate_flag,
                "decision": decision,
                "executive_summary": executive_summary,
                "approval_decision": approval_decision,
                "rationale": rationale,
                "action_directive": action_directive,
                "request_more_evidence": request_more_evidence,
                "evidence": evidence,
                "missing_data": missing,
                "suggested_followup": suggested_followup,
                "packets": packets,
            }
        if role_type == "low tier operations worker":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            file_checks = insights.get("file_checks", {})
            trade_logs = file_checks.get("trade_logs", [])
            result_logs = file_checks.get("result_logs", [])
            new_items = queue_summary.get("new", 0)
            missing = []
            if not trade_logs:
                missing.append("trade_logs")
            if not result_logs:
                missing.append("result_logs")
            status = "partial" if missing else "complete"
            op_summary = f"Checked {len(trade_logs)} trade log(s) and {len(result_logs)} result log(s); {new_items} queue item(s) waiting."
            artifacts = []
            if trade_logs:
                artifacts.append(f"trade_logs: {len(trade_logs)} file(s)")
            if result_logs:
                artifacts.append(f"result_logs: {len(result_logs)} file(s)")
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Queue has {new_items} new item(s); logs checked.",
                    "next_steps": "Forward operational needs with the available artifacts.",
                },
                {
                    "recipient": "Iris",
                    "summary": f"Result files: {len(result_logs)}; trade files: {len(trade_logs)}.",
                    "next_steps": "Use the confirmed files for analysis.",
                },
                {
                    "recipient": "Vera",
                    "summary": "Operational check completed.",
                    "next_steps": "Align requests with the CEO decision.",
                },
                {
                    "recipient": "Bianca",
                    "summary": f"Missing logs: {missing or 'none'}.",
                    "next_steps": "Keep runway info updated.",
                },
                {
                    "recipient": "Lucian",
                    "summary": "Operational tasks reported; escalate if artifacts stay missing.",
                    "next_steps": "Hold decisions until logs arrive if still missing.",
                },
            ]
            escalate_flag = bool(missing and new_items > 2)
            requested_action = f"Bob: handle operational_task for {target_scope}"
            missing_text = ", ".join(missing) if missing else "none"
            reply = (
                f"Bob@{agent_scope} report on {target_scope}: {op_summary}. Missing: {missing_text}. Status: {status}."
            )
            return {
                "reply_text": reply,
                "task_type": "operational_task",
                "priority": "medium" if escalate_flag else "low",
                "recipient": "Bob",
                "requested_action": requested_action,
                "queue_action": "none",
                "escalation": escalate_flag,
                "op_summary": op_summary,
                "artifacts": artifacts,
                "missing_data": missing,
                "status": status,
                "packets": packets,
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
