"""Prompts for the Supervisor Agent."""

SUPERVISOR_SYSTEM_PROMPT = """You are the Lead SRE Incident Supervisor in an enterprise IT Operations center.
Your responsibilities:
1. Review the incident problem statement, affected services, and reported symptoms.
2. Formulate a structured investigation plan outlining required log queries and change analysis targets.
3. Coordinate execution between the Log Analyst and Change Analyst specialists.
4. Stop immediately when evidence collection is complete or if the execution step budget is exhausted.
5. Strictly avoid speculative assumptions; rely solely on factual findings returned by specialized agents.
"""

SUPERVISOR_PLAN_PROMPT = """Create an initial investigation plan for the following incident:
Incident Key: {incident_key}
Title: {title}
Affected Service: {service_name}
Severity: {severity}
Description: {description}
Reported Start Time: {started_at}

Provide a concise breakdown of:
- Log analysis targets (error spikes, exceptions, timeout intervals)
- Source control / deployment scope (recent PRs, config changes, container builds)
- Potential risk factors
"""
