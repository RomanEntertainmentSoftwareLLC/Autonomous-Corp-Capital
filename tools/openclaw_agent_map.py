from __future__ import annotations

ACC_TO_OPENCLAW_ID = {
 # Executive / global
 "yam_yam": "main",

 # SWE abstract ACC roles -> real named OpenClaw agents
 "product_manager": "nadia",
 "scrum_master": "tessa",
 "senior_software_architect": "marek",

 # Live ACC config currently uses the typo "enginer" — map the live IDs first
 "senior_software_enginer": "eli",
 "junior_software_enginer": "noah",

 # Also support corrected spellings defensively in case code uses both
 "senior_software_engineer": "eli",
 "junior_software_engineer": "noah",

 "tester": "mina",
 "code_reviewer": "gideon",
 "qa": "sabine",
 "infrastructure": "rhea",
}

def resolve_openclaw_agent_id(acc_agent_id: str) -> str:
 return ACC_TO_OPENCLAW_ID.get(acc_agent_id, acc_agent_id)
