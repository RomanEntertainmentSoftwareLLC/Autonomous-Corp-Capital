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
        if role_type == "evolution":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            lifecycle = insights.get("metadata_summary", "unknown")
            manager_action = insights.get("manager_action") or {}
            manager_recommendation = manager_action.get("recommendation")
            reports = insights.get("agent_reports", {})
            rowan_summary = (reports.get("Rowan") or [])[-1] if reports.get("Rowan") else {}
            vera_reports = reports.get("Vera") or []
            latest_vera = vera_reports[-1] if vera_reports else {}
            vera_recommendation = manager_recommendation or latest_vera.get("recommendation")
            bianca_posture = (reports.get("Bianca") or [])[-1] if reports.get("Bianca") else {}
            missing = insights.get("missing_data", [])
            new_tasks = queue_summary.get("new", 0)
            evidence = []
            if lifecycle:
                evidence.append(f"Lifecycle: {lifecycle}")
            if vera_recommendation:
                evidence.append(f"Vera: {vera_recommendation}")
            risk_notes = []
            if missing:
                risk_notes.append(f"Missing data: {', '.join(missing)}")
            if new_tasks and new_tasks > 2:
                risk_notes.append("Queue pressure suggests caution before mutating.")
            evolution_summary = f"{target_scope} is {lifecycle} with {new_tasks} new queue item(s)."
            mutation_proposal = (
                f"Test a {target_scope}-focused parameter sweep: reduce order_size by 10% and tighten ema_fast/sma_slow spread while monitoring {manager_recommendation or 'manager context'}."
                if vera_recommendation or manager_recommendation else
                f"Hold and gather the missing logs before drafting a mutation."
            )
            candidate_parameters = [
                "order_size -10%",
                "ema_fast +2 / ema_slow +4",
                "stop_loss tighten 0.25%",
            ]
            candidate_strategies = [
                vera_recommendation or "current strategy variant",
                "fork next regime-specific EMA/RSI mix",
            ]
            rationale = f"Mutation rationale: {target_scope} lifecycle {lifecycle}; queue items {new_tasks}; evidence: " + ("; ".join(evidence) or "none" )
            suggested_followup = (
                "Ask Atlas to simulate the proposed parameter sweep once the missing logs arrive."
                if missing else "Send the mutation proposal to Atlas and Vera for simulation."
            )
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Prepared evolution proposal for {target_scope}.",
                    "next_steps": "Route artifacts to Atlas and Vera.",
                },
                {
                    "recipient": "Atlas",
                    "summary": mutation_proposal,
                    "next_steps": "Simulate the candidate parameters before Lucian reviews.",
                },
                {
                    "recipient": "Vera",
                    "summary": f"Align management plans with the proposed mutation: {vera_recommendation or 'no fresh recommendation'}.",
                    "next_steps": "Confirm support before executing.",
                },
                {
                    "recipient": "Lucian",
                    "summary": f"Evolution request waits on {'logs' if missing else 'sim results'}.",
                    "next_steps": "Approve or hold the plan after data arrives.",
                },
            ]
            return {
                "reply_text": f"Sloane@{agent_scope} suggests: {mutation_proposal}",
                "mutation_proposal": mutation_proposal,
                "evolution_summary": evolution_summary,
                "candidate_parameters": candidate_parameters,
                "candidate_strategies": candidate_strategies,
                "rationale": rationale,
                "risk_notes": risk_notes,
                "suggested_followup": suggested_followup,
                "packets": packets,
                "escalation": bool(missing and new_tasks > 2),
                "queue_action": "none",
                "task_type": "evolution",
                "priority": "medium",
            }
        if role_type == "market simulator":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            lifecycle = insights.get("metadata_summary", "unknown")
            agent_reports = insights.get("agent_reports", {})
            sloan_reports = agent_reports.get("Sloane") or []
            latest_sloane = sloan_reports[-1] if sloan_reports else {}
            proposal = latest_sloane.get("mutation_proposal") or "No recent mutation proposal"
            missing = insights.get("missing_data", [])
            new_tasks = queue_summary.get("new", 0)
            confidence = "low" if missing else "high" 
            if missing and new_tasks > 1:
                confidence = "low"
            elif missing:
                confidence = "medium"
            elif new_tasks > 3:
                confidence = "high"
            simulation_summary = f"{target_scope} simulation assesses {proposal} under {lifecycle} conditions."
            candidate_win_pct = max(45, 80 - len(missing) * 5)
            scenario_results = f"Candidate beats baseline in ~{candidate_win_pct}% of sandbox runs while volatility stays moderated."
            comparative_outcomes = [
                f"Candidate: {proposal}.",
                f"Baseline: retain current strategy until approval.",
            ]
            limitations = (
                f"Missing data: {', '.join(missing)}." if missing else "Inputs appear complete for a controlled run."
            )
            recommendation = (
                "Run the highlighted scenario in Atlas with the proposed parameters."
                if not missing else "Delay until Sloane or Bob refreshes the missing artifacts."
            )
            suggested_followup = (
                "Notify Sloane and Vera once the simulation results land so Lucian can decide."
                if not missing else "Collect the missing logs and rerun the scenario."
            )
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Simulation queued for {target_scope}.",
                    "next_steps": "Share results with Vera and Lucian once available.",
                },
                {
                    "recipient": "Sloane",
                    "summary": f"Simulating proposed mutation: {proposal}.",
                    "next_steps": "Ready the mutation detail sheet after the sim completes.",
                },
                {
                    "recipient": "Vera",
                    "summary": f"Align management plans with the simulation: {proposal[:60] if proposal else 'n/a'}.",
                    "next_steps": "Confirm support before escalating to Lucian.",
                },
                {
                    "recipient": "Lucian",
                    "summary": f"Simulation confidence {confidence}; {target_scope} needs review.",
                    "next_steps": "Approve simulation findings or ask for more runs.",
                },
            ]
            return {
                "reply_text": f"Atlas@{agent_scope} simulated scenario: {scenario_results}.",
                "simulation_summary": simulation_summary,
                "scenario_results": scenario_results,
                "comparative_outcomes": comparative_outcomes,
                "confidence": confidence,
                "limitations": limitations,
                "recommendation": recommendation,
                "suggested_followup": suggested_followup,
                "packets": packets,
                "escalation": bool(missing and new_tasks > 3),
                "queue_action": "none",
                "task_type": "simulation_review",
                "priority": "medium",
            }

        if role_type == "market simulator":
            insights = prompt.get("company_insights", {})
            queue_summary = prompt.get("queue_summary", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            lifecycle = insights.get("metadata_summary", "unknown")
            agent_reports = insights.get("agent_reports", {})
            sloan_reports = agent_reports.get("Sloane") or []
            latest_sloane = sloan_reports[-1] if sloan_reports else {}
            proposal = latest_sloane.get("mutation_proposal") or "No recent mutation proposal"
            missing = insights.get("missing_data", [])
            new_tasks = queue_summary.get("new", 0)
            confidence = "low" if missing else "high" 
            if missing and new_tasks > 1:
                confidence = "low"
            elif missing:
                confidence = "medium"
            elif new_tasks > 3:
                confidence = "high"
            simulation_summary = f"{target_scope} simulation assesses {proposal} under {lifecycle} conditions."
            candidate_win_pct = max(45, 80 - len(missing) * 5)
            scenario_results = f"Candidate beats baseline in ~{candidate_win_pct}% of sandbox runs while volatility stays moderated."
            comparative_outcomes = [
                f"Candidate: {proposal}.",
                f"Baseline: retain current strategy until approval.",
            ]
            limitations = (
                f"Missing data: {', '.join(missing)}." if missing else "Inputs appear complete for a controlled run."
            )
            recommendation = (
                "Run the highlighted scenario in Atlas with the proposed parameters."
                if not missing else "Delay until Sloane or Bob refreshes the missing artifacts."
            )
            suggested_followup = (
                "Notify Sloane and Vera once the simulation results land so Lucian can decide."
                if not missing else "Collect the missing logs and rerun the scenario."
            )
            packets = [
                {
                    "recipient": "Pam",
                    "summary": f"Simulation queued for {target_scope}.",
                    "next_steps": "Share results with Vera and Lucian once available.",
                },
                {
                    "recipient": "Sloane",
                    "summary": f"Simulating proposed mutation: {proposal}.",
                    "next_steps": "Ready the mutation detail sheet after the sim completes.",
                },
                {
                    "recipient": "Vera",
                    "summary": f"Align management plans with the simulation: {proposal[:60] if proposal else 'n/a'}.",
                    "next_steps": "Confirm support before escalating to Lucian.",
                },
                {
                    "recipient": "Lucian",
                    "summary": f"Simulation confidence {confidence}; {target_scope} needs review.",
                    "next_steps": "Approve simulation findings or ask for more runs.",
                },
            ]
            return {
                "reply_text": f"Atlas@{agent_scope} simulated scenario: {scenario_results}.",
                "simulation_summary": simulation_summary,
                "scenario_results": scenario_results,
                "comparative_outcomes": comparative_outcomes,
                "confidence": confidence,
                "limitations": limitations,
                "recommendation": recommendation,
                "suggested_followup": suggested_followup,
                "packets": packets,
                "escalation": bool(missing and new_tasks > 3),
                "queue_action": "none",
                "task_type": "simulation_review",
                "priority": "medium",
            }

        if role_type == "archivist":
            insights = prompt.get("company_insights", {})
            target_scope = prompt.get("target_scope", prompt.get("scope", ""))
            queue_summary = prompt.get("queue_summary", {})
            agent_reports = insights.get("agent_reports", {})
            latest_iris = (agent_reports.get("Iris") or [])[-1] if agent_reports.get("Iris") else {}
            latest_vera = (agent_reports.get("Vera") or [])[-1] if agent_reports.get("Vera") else {}
            latest_rowan = (agent_reports.get("Rowan") or [])[-1] if agent_reports.get("Rowan") else {}
            latest_bianca = (agent_reports.get("Bianca") or [])[-1] if agent_reports.get("Bianca") else {}
            latest_lucian = (agent_reports.get("Lucian") or [])[-1] if agent_reports.get("Lucian") else {}
            latest_bob = (agent_reports.get("Bob") or [])[-1] if agent_reports.get("Bob") else {}
            latest_sloane = (agent_reports.get("Sloane") or [])[-1] if agent_reports.get("Sloane") else {}
            latest_atlas = (agent_reports.get("Atlas") or [])[-1] if agent_reports.get("Atlas") else {}
            missing = insights.get("missing_data", [])
            decisions = []
            if latest_lucian.get('decision'):
                decisions.append(f"Lucian: {latest_lucian.get('decision')}")
            if latest_vera.get('recommendation'):
                decisions.append(f"Vera: {latest_vera.get('recommendation')}")
            if latest_sloane.get('mutation_proposal'):
                decisions.append(f"Sloane proposed: {latest_sloane.get('mutation_proposal')[:60]}")
            lessons = []
            if missing:
                lessons.append(f"Missing artifacts: {', '.join(missing)}; follow-up needed before firm decisions.")
            if latest_atlas.get('confidence') == 'low':
                lessons.append("Simulations remain inconclusive; avoid committing.")
            unresolved = missing[:]
            if latest_lucian.get('escalation'):
                unresolved.append("Escalation flagged during last executive decision.")
            archival_summary = (
                f"Recent activity: {decisions[0] if decisions else 'No recorded decisions yet.'}"
            )
            decision_record = decisions or ["No firm decisions captured yet."]
            event_summary = []
            if latest_iris.get('analysis_summary'):
                event_summary.append(f"Iris: {latest_iris.get('analysis_summary')}")
            if latest_rowan.get('research_summary'):
                event_summary.append(f"Rowan: {latest_rowan.get('research_summary')}")
            memory_digest = (
                f"Bianca posture {latest_bianca.get('spending_posture', 'unknown')} with {latest_bob.get('op_summary', 'no ops summary')}.")
            timeline = [
                f"Lucian: {latest_lucian.get('decision', 'no decision')}",
                f"Atlas: {latest_atlas.get('scenario_results', 'no sim yet')}",
            ]
            summary_text = (
                f"June@{agent_scope} archive: {archival_summary} Lessons: {lessons or ['Records lean']}"
            )
            packets = [
                {
                    "recipient": "Pam",
                    "summary": "Archived snapshot ready.",
                    "next_steps": "Share with leadership and vault details.",
                },
                {
                    "recipient": "Lucian",
                    "summary": f"Recent timeline: {decision_record[0]}.",
                    "next_steps": "Review the lessons before the next directive.",
                },
                {
                    "recipient": "Vera",
                    "summary": "Context digest for your next recommendation.",
                    "next_steps": "Ensure decisions appear in the next packet.",
                },
                {
                    "recipient": "YamYam",
                    "summary": f"Archivist notes {len(unresolved)} unresolved issues.",
                    "next_steps": "Monitor the missing artifacts.",
                },
            ]
            return {
                "reply_text": summary_text,
                "archival_summary": archival_summary,
                "decision_record": decision_record,
                "event_summary": event_summary,
                "memory_digest": memory_digest,
                "timeline": timeline,
                "lessons_learned": lessons or ["Records currently incomplete."],
                "unresolved_issues": unresolved,
                "packets": packets,
                "escalation": bool(unresolved),
                "queue_action": "none",
                "task_type": "archival_summary",
                "priority": "medium",
            }
        if role_type.lower() == "junior software engineer":
            insights = prompt.get("company_insights", {})
            blockers = insights.get("missing_data", [])
            implementation_summary = "I can take on the helper tasks once the blockers clear."
            subtask_plan = ["Fix the CLI helper and add logging."]
            packets = [
                {
                    "recipient": "Tester",
                    "summary": "Junior implementation ready for testing.",
                    "next_steps": "Review the helper changes.",
                },
                {
                    "recipient": "Reviewer",
                    "summary": "Noah implemented the small bug fix.",
                    "next_steps": "Ensure integration is safe.",
                },
            ]
            return {
                "reply_text": f"Noah@{agent_scope} reports {len(blockers)} blockers before I proceed.",
                "implementation_summary": implementation_summary,
                "subtask_plan": subtask_plan,
                "blockers": blockers or ["None"],
                "packets": packets,
                "task_type": "implementation_review",
                "priority": "medium",
                "escalation": bool(blockers),
                "queue_action": "none",
            }

        if role_type.lower() == "senior software engineer":
            insights = prompt.get("company_insights", {})
            implementation_summary = "Implementation plan ready after Marek's approval."
            code_plan = ["Wire the rebuilt runtime into the new modules."]
            integration_notes = ["Watch the treasury/risk interplay."]
            blockers = insights.get("missing_data", [])
            packets = [
                {
                    "recipient": "Junior SWE",
                    "summary": "Implementation scope set by Eli.",
                    "next_steps": "Pick up the confirmed work.",
                },
                {
                    "recipient": "Tester",
                    "summary": "Integration points flagged.",
                    "next_steps": "Prep test plan.",
                },
            ]
            return {
                "reply_text": f"Eli@{agent_scope} notes {len(blockers)} blockers and integration points.",
                "implementation_summary": implementation_summary,
                "code_plan": code_plan,
                "integration_notes": integration_notes,
                "blockers": blockers or ["None"],
                "packets": packets,
                "task_type": "implementation_review",
                "priority": "medium",
                "escalation": bool(blockers),
                "queue_action": "none",
            }

        if role_type.lower() == "senior software architect":
            insights = prompt.get("company_insights", {})
            blockers = insights.get("missing_data", [])
            module_notes = ["Refactor tools/agent_runtime to respect single duties"]
            recommendation = (
                "Extract shared runtime helpers into a dedicated architecture layer before new roles are added."
                if blockers else "Keep current structure but document the key interfaces before extending."
            )
            packets = [
                {
                    "recipient": "Senior SWE",
                    "summary": "Refactor guided by Marek",
                    "next_steps": "Plan the architecture phase.",
                },
                {
                    "recipient": "Infrastructure",
                    "summary": "Coordinate shared runtime changes.",
                    "next_steps": "Ensure deployments honor the new modules.",
                },
            ]
            return {
                "reply_text": f"Marek@{agent_scope} sees {len(module_notes)} structural concerns.",
                "architecture_summary": "/tools/agent_runtime and prompt helpers need clearer boundaries.",
                "refactor_recommendation": recommendation,
                "module_guidance": module_notes,
                "tech_debt_warnings": blockers or ["None"],
                "packets": packets,
                "escalation": bool(blockers),
                "queue_action": "none",
                "task_type": "architecture_review",
                "priority": "medium",
            }

        if role_type.lower() == "infrastructure":
            summary = "Infra status: clean branch but awaiting Sabine's QA sign-off."
            merge_plan = ["Wait for Gideon approval before merging."]
            release_notes = ["Tag release after QA sign-off."]
            rollback_guidance = "Keep the previous tag handy in case regressions appear."
            packets = [
                {
                    "recipient": "Infrastructure",
                    "summary": "Branch hygiene needs confirmation.",
                    "next_steps": "Hold until QA and review gates clear.",
                },
                {
                    "recipient": "Jacob",
                    "summary": "Infra notes ready for review.",
                    "next_steps": "Approve merge once gates pass.",
                },
            ]
            return {
                "reply_text": f"Rhea@{agent_scope} says: {summary}",
                "infra_summary": summary,
                "merge_plan": merge_plan,
                "release_notes": release_notes,
                "rollback_guidance": rollback_guidance,
                "packets": packets,
                "task_type": "infrastructure_review",
                "priority": "medium",
                "escalation": False,
                "queue_action": "none",
            }

        if role_type.lower() == "qa":
            product_summary = response.get("product_summary") or prompt.get("product_summary") or "Product clarity pending."
            acceptance_criteria = (
                response.get("acceptance_criteria") or prompt.get("acceptance_criteria") or []
            )
            test_summary = response.get("test_summary") or prompt.get("test_summary") or "Tests pending execution."
            failing_cases = (
                response.get("failing_cases")
                or response.get("blockers")
                or []
            )
            coverage_notes = response.get("coverage_notes") or []
            review_summary = response.get("review_summary") or prompt.get("review_summary") or "Review pending."
            review_findings = response.get("review_findings") or []
            implementation_summary = (
                response.get("implementation_summary") or prompt.get("implementation_summary") or "Implementation details missing."
            )
            blockers = response.get("blockers") or []
            task_summary = response.get("task_summary") or prompt.get("task_summary") or "No task breakdown yet."
            engineering_tasks = response.get("engineering_tasks") or prompt.get("engineering_tasks") or []
            regression_risks = (
                response.get("regression_risks")
                or failing_cases
                or []
            )
            ship_readiness = "Ready" if not failing_cases and not regression_risks else "Not ready"
            behavior_notes = [product_summary, review_summary, implementation_summary]
            behavior_notes.extend([note for note in acceptance_criteria + coverage_notes + review_findings if note])
            if task_summary:
                behavior_notes.append(task_summary)
            behavior_notes.extend([t for t in engineering_tasks if t])
            qa_summary = (
                f"Sabine@{agent_scope} reports {len(failing_cases)} failing case(s); readiness={ship_readiness}."
            )
            packets = [
                {
                    "recipient": "Infrastructure",
                    "summary": "QA status influences release timing.",
                    "next_steps": "Hold or reroute merges until Sabine has confidence.",
                },
                {
                    "recipient": "Code Reviewer",
                    "summary": "QA flagged behavioral or regression issues.",
                    "next_steps": "Patch the failing flows and rerun tests.",
                },
                {
                    "recipient": "Scrum Master",
                    "summary": "QA is tracking blockers for the current sprint.",
                    "next_steps": "Reprioritize tasks to address the failures first.",
                },
            ]
            return {
                "reply_text": qa_summary,
                "qa_summary": qa_summary,
                "behavior_notes": behavior_notes,
                "regression_risks": regression_risks,
                "ship_readiness": ship_readiness,
                "packets": packets,
                "task_type": "qa_review",
                "priority": "medium",
                "escalation": bool(regression_risks),
                "queue_action": "none",
            }
        if role_type.lower() == "code reviewer":
            insights = prompt.get("company_insights", {})
            snippet = insights.get("manager_action", {}).get("recommendation")
            issues = insights.get("missing_data", [])
            review_summary = "Code is functional but the module needs clearer boundaries."
            recommendation = "Revise before QA; address architecture drift." if issues else "Approve for QA review."
            quality_notes = ["Watch lifecycle coupling tightness."]
            blockers = issues
            packets = [
                {
                    "recipient": "Eli",
                    "summary": "Code needs maintainability polish.",
                    "next_steps": "Refactor per Marek’s guidance.",
                },
                {
                    "recipient": "QA",
                    "summary": "Reviewer has flagged issues.",
                    "next_steps": "Wait for revisions before testing.",
                },
            ]
            return {
                "reply_text": f"Gideon@{agent_scope} says: {review_summary} Recommendation: {recommendation}",
                "review_summary": review_summary,
                "recommendation": recommendation,
                "code_quality_notes": quality_notes,
                "blockers": blockers,
                "packets": packets,
                "task_type": "code_review",
                "priority": "medium",
                "escalation": bool(blockers),
                "queue_action": "none",
            }

        if role_type.lower() == "tester":
            insights = prompt.get("company_insights", {})
            pass_fail = insights.get("missing_data", [])
            test_summary = "Test run captured; pass/fail updated"
            coverage_notes = ["Missing coverage around config parsing"]
            packets = [
                {
                    "recipient": "Eli",
                    "summary": "Testing uncovered failures.",
                    "next_steps": "Address failing cases before review.",
                },
                {
                    "recipient": "QA",
                    "summary": "Verification needs more coverage.",
                    "next_steps": "Add regression coverage.",
                },
            ]
            return {
                "reply_text": f"Mina@{agent_scope} details {len(pass_fail)} failing cases.",
                "test_summary": test_summary,
                "pass_fail": pass_fail or ["All green"],
                "coverage_notes": coverage_notes,
                "blockers": pass_fail,
                "packets": packets,
                "task_type": "test_review",
                "priority": "medium",
                "escalation": bool(pass_fail),
                "queue_action": "none",
            }

        if role_type.lower() == "scrum master":
            insights = prompt.get("company_insights", {})
            blockers = insights.get("missing_data", [])
            task_summary = f"{prompt.get('message', 'Unknown request')} needs {len(blockers)} blockers resolved."
            task_breakdown = ["Break into SWE + QA tickets"]
            next_steps = ["Resolve blockers before moving to implementation"]
            packets = [
                {
                    "recipient": "SWE",
                    "summary": "Tasks ready for sprint planning.",
                    "next_steps": "Pick up the highest-priority ticket.",
                },
                {
                    "recipient": "QA",
                    "summary": "Testing scope clarified.",
                    "next_steps": "Review the acceptance criteria.",
                },
            ]
            return {
                "reply_text": f"Tessa@{agent_scope} frames {task_summary}.",
                "task_summary": task_summary,
                "task_breakdown": task_breakdown,
                "blockers": blockers,
                "next_steps": next_steps,
                "packets": packets,
                "task_type": "execution_review",
                "priority": "medium",
                "escalation": False,
                "queue_action": "none",
            }

        if role_type.lower() == "product manager":
            summary = "Nadia sees the backlog leaning toward infrastructure gaps."
            priority_backlog = ["Infrastructure: stabilize CLI", "Warehouse: clean reporting pipeline"]
            recommendation = "Defer new experiments until these critical blockers clear."
            acceptance_criteria = ["Define success metrics", "Document QA path"]
            packets = [
                {
                    "recipient": "Scrum Master",
                    "summary": "Shared backlog trimmed to actionable work.",
                    "next_steps": "Prioritize the blockers during planning.",
                },
                {
                    "recipient": "YamYam",
                    "summary": "Product view updated; infrastructure gaps first.",
                    "next_steps": "Review before adding new company directives.",
                },
            ]
            return {
                "reply_text": f"Nadia@{agent_scope} recommends: {recommendation}",
                "product_summary": summary,
                "priority_backlog": priority_backlog,
                "recommendation": recommendation,
                "acceptance_criteria": acceptance_criteria,
                "packets": packets,
                "task_type": "product_review",
                "priority": "medium",
                "escalation": False,
                "queue_action": "none",
            }

        if role_type.lower() == "master cfo":
            finance_insights = prompt.get("global_finance_insights", {})
            companies = finance_insights.get("companies", [])
            inefficiencies = finance_insights.get("inefficiencies", [])
            sustainability = finance_insights.get("sustainability", "unknown")
            summary = f"Portfolio health {sustainability}; {len(inefficiencies)} inefficiency flag(s)."
            recommendation = (
                "Rebalance toward efficient companies and pause noisy spend."
                if inefficiencies else "Flag for review and keep the current mix."
            )
            capital_recommendation = "Preserve cash around the weak performers." if inefficiencies else "Monitor performance before reallocating."
            exposure = [c for c in companies if c.get("allocation_percent") not in (None, "unknown") and float(c.get("allocation_percent")) > 65]
            inefficient_ids = [f"{c['company_id']} ({c.get('allocation_percent', '??')}%)" for c in inefficiencies]
            packets = [
                {
                    "recipient": "Selene",
                    "summary": summary,
                    "next_steps": "Align treasury posture with this portfolio view.",
                },
                {
                    "recipient": "Helena",
                    "summary": f"Inefficient companies: {', '.join(inefficient_ids) or 'none'}.",
                    "next_steps": "Hold risky proposals until resolved.",
                },
                {
                    "recipient": "YamYam",
                    "summary": "Portfolio finance intelligence ready.",
                    "next_steps": "Use this before approving new directions.",
                },
            ]
            return {
                "reply_text": f"Vivienne@{agent_scope} notes {summary} Recommendation: {recommendation}.",
                "global_financial_summary": summary,
                "portfolio_efficiency": sustainability,
                "capital_recommendation": capital_recommendation,
                "sustainability_note": sustainability,
                "inefficient_companies": inefficient_ids,
                "ship_to_risk": "Escalate inefficiencies to Helena." if inefficient_ids else "No extra risk escalation needed.",
                "packets": packets,
                "escalation": bool(inefficiencies),
                "queue_action": "none",
                "task_type": "finance_review",
                "priority": "medium",
            }
        if role_type.lower() == "risk officer":
            risk_insights = prompt.get("global_risk_insights", {})
            companies = risk_insights.get("companies", [])
            escalations = risk_insights.get("escalations", [])
            risk_flags = risk_insights.get("risk_flags", [])
            overexposed = [c for c in companies if c.get("allocation_percent") not in (None, "unknown") and str(c.get("allocation_percent")) not in ("None",) and float(c.get("allocation_percent")) > 65] if companies else []
            exposure_summary = [f"{c['company_id']}: {c['allocation_percent']}%" for c in overexposed]
            summary = f"Risk summary: {len(overexposed)} overexposed company(s); escalations {len(escalations)}; flags {len(risk_flags)}."
            veto = "Do not proceed" if risk_flags or overexposed else "Allow caution with close monitoring."
            caution = risk_flags or ["No immediate red flags"]
            packets = [
                {
                    "recipient": "Selene",
                    "summary": summary,
                    "next_steps": "Coordinate with treasury before approving new allocations.",
                },
                {
                    "recipient": "YamYam",
                    "summary": f"Escalations: {len(escalations)}; risk_flags: {len(risk_flags)}.",
                    "next_steps": "Assess breach responses if any flags are critical.",
                },
                {
                    "recipient": "Lucian",
                    "summary": "Risk posture ready for strategy review.",
                    "next_steps": "Hold or adjust actions per this counsel.",
                },
            ]
            return {
                "reply_text": f"Helena@{agent_scope} warns: {summary} Veto: {veto}.",
                "global_risk_summary": summary,
                "veto_decision": veto,
                "caution_notes": caution,
                "drawdown_warnings": overexposed,
                "overexposure_flags": exposure_summary,
                "recommended_constraints": "No new risks until the escalations clear." if escalations else "Proceed with approved requests.",
                "packets": packets,
                "escalation": bool(escalations),
                "queue_action": "none",
                "task_type": "risk_review",
                "priority": "high" if escalations else "medium",
            }

        if role_type == "master cfo":
            finance_insights = prompt.get("global_finance_insights", {})
            companies = finance_insights.get("companies", [])
            inefficiencies = finance_insights.get("inefficiencies", [])
            sustainability = finance_insights.get("sustainability", "unknown")
            summary = f"Portfolio health {sustainability}; {len(inefficiencies)} inefficiency flag(s)."
            recommendation = (
                "Rebalance toward efficient companies and pause noisy spend."
                if inefficiencies else "Flag for review and keep the current mix."
            )
            capital_recommendation = ("Preserve cash around weak performers." if inefficiencies else "Monitor their performance before reallocating.")
            exposure = [c for c in companies if c.get("allocation_percent") not in (None, "unknown") and float(c.get("allocation_percent")) > 65]
            inefficient_ids = [f"{c['company_id']} ({c.get('allocation_percent', '??')}%)" for c in inefficiencies]
            packets = [
                {
                    "recipient": "Selene",
                    "summary": summary,
                    "next_steps": "Align treasury posture with this portfolio view.",
                },
                {
                    "recipient": "Helena",
                    "summary": f"Inefficient companies: {', '.join(inefficient_ids) or 'none'}.",
                    "next_steps": "Hold risky proposals until resolved.",
                },
                {
                    "recipient": "YamYam",
                    "summary": "Portfolio finance intelligence ready.",
                    "next_steps": "Use this before approving new directions.",
                },
            ]
            return {
                "reply_text": f"Vivienne@{agent_scope} notes {summary} Recommendation: {recommendation}.",
                "global_financial_summary": summary,
                "portfolio_efficiency": sustainability,
                "capital_recommendation": capital_recommendation,
                "sustainability_note": sustainability,
                "inefficient_companies": inefficient_ids,
                "ship_to_risk": "Refer inefficiencies to Helena." if inefficient_ids else "No extra risk flags.",
                "packets": packets,
                "escalation": bool(inefficiencies),
                "queue_action": "none",
                "task_type": "finance_review",
                "priority": "medium",
            }

        if role_type == "master treasurer":
            global_insights = prompt.get("global_insights", {})
            def _to_pct(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
            treasury = global_insights.get("treasury_snapshot", {})
            companies = global_insights.get("companies", [])
            active_count = global_insights.get("active_company_count", len(companies))
            reserve_level = treasury.get("reserve_capital") or treasury.get("reserve_percent") or "unknown"
            overexposed = [
                c for c in companies
                if _to_pct(c.get("allocation_percent")) is not None and _to_pct(c.get("allocation_percent")) > 70
            ]
            overexposure_warnings = [f"{c['company_id']} at {c['allocation_percent']}%" for c in overexposed]
            summary = f"Parent treasury reserves {reserve_level}; {active_count} tracked companies."
            recommendation = (
                "Preserve capital and hold funding requests while reserves refresh."
                if overexposure_warnings or reserve_level in ("unknown", 0)
                else "Allow measured allocations where company CFOs report stable posture."
            )
            reserve_posture = "cautious" if overexposure_warnings else "steady"
            allowance_recommendation = "Tighten allowances for the next cycle." if overexposure_warnings else "Maintain current allowances with close monitoring."
            rationale = f"Reserves {reserve_level}; overexposed companies: {len(overexposed)}; active: {active_count}."
            packets = [
                {
                    "recipient": "YamYam",
                    "summary": summary,
                    "next_steps": "Discuss capital posture before approving extra spend.",
                },
                {
                    "recipient": "Risk Officer",
                    "summary": f"Overexposure warnings: {', '.join(overexposure_warnings) if overexposure_warnings else 'none'}.",
                    "next_steps": "Assess risk limits and notify companies.",
                },
                {
                    "recipient": "Bianca",
                    "summary": "Hold on new requests until global reserves stabilize.",
                    "next_steps": "Align local spending posture with the treasury note.",
                },
                {
                    "recipient": "Lucian",
                    "summary": "Treasure summary ready for leadership.",
                    "next_steps": "Use this before deciding on new company actions.",
                },
            ]
            return {
                "reply_text": f"Selene@{agent_scope} notes {summary}. {recommendation}",
                "global_treasury_summary": summary,
                "allocation_recommendation": recommendation,
                "reserve_posture": reserve_posture,
                "allowance_recommendation": allowance_recommendation,
                "overexposure_warnings": overexposure_warnings,
                "financial_rationale": rationale,
                "packets": packets,
                "escalation": bool(overexposure_warnings),
                "queue_action": "none",
                "task_type": "treasury_review",
                "priority": "medium",
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
