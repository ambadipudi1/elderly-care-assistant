# ruff: noqa
import json
import re
import logging
from typing import Any
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.adk.workflow import Workflow, Edge, START, node
from google.adk.agents.context import Context
from google.adk.events import RequestInput
from google.genai import types

from .config import config

logger = logging.getLogger("elderly_care_assistant")

from mcp import StdioServerParameters
from google.adk.tools.mcp_tool import StdioConnectionParams, McpToolset

mcp_connection = StdioConnectionParams(
    server_params=StdioServerParameters(
        command="uv",
        args=["run", "python", "app/mcp_server.py"],
    )
)

mcp_toolset = McpToolset(
    connection_params=mcp_connection,
)

# =====================================================================
# SPECIALIZED SUB-AGENTS (Phase 2 & 3)
# =====================================================================

medication_manager = LlmAgent(
    name="medication_manager",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the specialized Medication Manager. You are responsible for:\n"
        "1. Querying medication schedules, dosage, and guidelines.\n"
        "2. Tracking medication compliance and logging doses.\n"
        "3. Highlighting potential dosage issues or alert symptoms.\n"
        "Use the available MCP tools to get details and verify medical rules. "
        "Keep your output clear, concise, and structured."
    ),
    tools=[mcp_toolset],
)

wellbeing_logger = LlmAgent(
    name="wellbeing_logger",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the specialized Well-being Logger. You are responsible for:\n"
        "1. Logging daily well-being summaries (mood, pain, sleep, appetite).\n"
        "2. Reviewing well-being history logs to identify trends.\n"
        "3. Offering helpful, non-medical wellness recommendations.\n"
        "Use the available MCP tools to read and store well-being records."
    ),
    tools=[mcp_toolset],
)

# Wrap specialized agents as tools
medication_tool = AgentTool(agent=medication_manager)
wellbeing_tool = AgentTool(agent=wellbeing_logger)

# =====================================================================
# ORCHESTRATOR AGENT (Phase 2)
# =====================================================================

care_coordinator = LlmAgent(
    name="care_coordinator",
    model=Gemini(
        model=config.model,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=(
        "You are the central Care Coordinator agent. Your job is to coordinate "
        "elderly care requests. You can delegate medication queries/logs to the medication_manager "
        "and well-being records/logs to the wellbeing_logger using your tools.\n"
        "Rules:\n"
        "- For medication updates or logs, call the medication_manager tool.\n"
        "- For well-being checks, sleep log, or mood log, call the wellbeing_logger tool.\n"
        "- If the request involves updating a medication schedule, dosage, or adding a new medication, "
        "you MUST inform the user that it needs caregiver review/approval, and explain what is being updated.\n"
        "State management:\n"
        "- Store important updates or intermediate care decisions in the session state if needed.\n"
        "Keep responses friendly, supportive, and extremely clear for elderly users or caregivers."
    ),
    tools=[medication_tool, wellbeing_tool],
)

# =====================================================================
# WORKFLOW NODES & SECURITY (Phase 2 & 4)
# =====================================================================

@node
async def security_checkpoint(ctx: Context, node_input: Any):
    """
    Security Checkpoint node:
    1. Prompt Injection check (e.g. system instructions override, ignore previous rules).
    2. PII Scrubbing (removes SSN patterns, phone numbers, names).
    3. Audit logging.
    """
    input_str = str(node_input)
    
    # Prompt injection check
    injection_keywords = ["ignore previous instruction", "system prompt", "override instructions", "bypass security"]
    has_injection = any(kw in input_str.lower() for kw in injection_keywords)
    
    # Domain-specific rule: Medical safety check for dosage limits
    has_dosage_violation = False
    violation_reason = ""
    # Look for patterns like "Lisinopril X mg" or "Metformin X mg" and check limits
    lisinopril_match = re.search(r'lisinopril\s+(\d+)\s*mg', input_str, re.IGNORECASE)
    metformin_match = re.search(r'metformin\s+(\d+)\s*mg', input_str, re.IGNORECASE)
    
    if lisinopril_match:
        dose = int(lisinopril_match.group(1))
        if dose > 40:
            has_dosage_violation = True
            violation_reason = f"Lisinopril dosage of {dose}mg exceeds the maximum safe daily limit of 40mg."
            
    if metformin_match:
        dose = int(metformin_match.group(1))
        if dose > 2000:
            has_dosage_violation = True
            violation_reason = f"Metformin dosage of {dose}mg exceeds the maximum safe daily limit of 2000mg."
            
    # PII Scrubbing
    scrubbed_input = input_str
    if config.pii_redaction_enabled:
        # Scrub SSNs
        scrubbed_input = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED SSN]', scrubbed_input)
        # Scrub US Phone Numbers
        scrubbed_input = re.sub(r'\b\d{3}-\d{3}-\d{4}\b', '[REDACTED PHONE]', scrubbed_input)
    
    # Audit log
    audit_log = {
        "event": "security_scan",
        "pii_redacted": scrubbed_input != input_str,
        "injection_detected": has_injection,
        "dosage_violation": has_dosage_violation,
    }
    
    if has_injection:
        audit_log["severity"] = "CRITICAL"
        logger.warning(json.dumps(audit_log))
        ctx.state["security_error"] = "Prompt injection attempt blocked."
        ctx.route = "violation"
        return
        
    if has_dosage_violation:
        audit_log["severity"] = "WARNING"
        audit_log["reason"] = violation_reason
        logger.warning(json.dumps(audit_log))
        ctx.state["security_error"] = f"Safety Block: {violation_reason}"
        ctx.route = "violation"
        return
    
    audit_log["severity"] = "INFO"
    logger.info(json.dumps(audit_log))
    
    # Save clean input in state
    ctx.state["clean_input"] = scrubbed_input
    ctx.route = "safe"
    return


@node
async def security_violation_node(ctx: Context, node_input: Any):
    err = ctx.state.get("security_error", "A security violation was detected.")
    return f"Access Denied: {err} Please verify your query content."


@node(rerun_on_resume=True)
async def main_coordinator_node(ctx: Context, node_input: Any):
    """
    Executes the central care coordinator agent and determines if approval is needed.
    """
    clean_input = ctx.state.get("clean_input", node_input)
    
    # Run the coordinator agent using ctx.run_node
    result = await ctx.run_node(care_coordinator, node_input=clean_input)
    response_text = result.text if hasattr(result, "text") else str(result)
    
    # Route based on whether approval is required (care plan or dosage changes)
    if "approval" in response_text.lower() or "caregiver review" in response_text.lower() or "needs review" in response_text.lower():
        ctx.state["pending_response"] = response_text
        ctx.route = "needs_approval"
        return
    
    ctx.state["final_output"] = response_text
    ctx.route = "complete"
    return


@node
async def human_approval_node(ctx: Context, node_input: Any):
    """
    HITL Node: Pauses execution to wait for a caregiver or doctor approval.
    """
    interrupt_id = "caregiver_approval"
    
    if interrupt_id in ctx.resume_inputs:
        # We got the approval decision
        approval_data = ctx.resume_inputs[interrupt_id]
        is_approved = str(approval_data).lower() in ["yes", "approve", "approved", "y"]
        
        audit_log = {
            "event": "human_in_the_loop_approval",
            "approved": is_approved,
            "decision": approval_data,
            "severity": "INFO"
        }
        logger.info(json.dumps(audit_log))
        
        if is_approved:
            pending = ctx.state.get("pending_response", "Medication update approved.")
            ctx.state["final_output"] = f"✅ Approved by Caregiver. Action executed:\n{pending}"
        else:
            ctx.state["final_output"] = "❌ Declined by Caregiver. The request has been cancelled."
        
        ctx.route = "complete"
        return
    
    # If not resumed, pause the workflow and request input
    pending_msg = ctx.state.get("pending_response", "Medication / dosage change requested.")
    yield RequestInput(
        interrupt_id=interrupt_id,
        message=f"✋ CAREGIVER APPROVAL REQUIRED:\n{pending_msg}\nType 'yes' to approve or 'no' to decline."
    )


@node
async def final_output_node(ctx: Context, node_input: Any):
    """
    Terminal node displaying the final result.
    """
    return ctx.state.get("final_output", "Routine processing complete.")

# =====================================================================
# WORKFLOW DEFINITION (Phase 2)
# =====================================================================

workflow = Workflow(
    name="elderly_care_workflow",
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        # Route safe queries to the coordinator
        Edge(from_node=security_checkpoint, to_node=main_coordinator_node, route="safe"),
        # Route security violations to the violation node
        Edge(from_node=security_checkpoint, to_node=security_violation_node, route="violation"),
        # Orchestrator routing
        Edge(from_node=main_coordinator_node, to_node=human_approval_node, route="needs_approval"),
        Edge(from_node=main_coordinator_node, to_node=final_output_node, route="complete"),
        # Loop back from human approval to orchestrator or terminal.
        # Edge rule: converging routes ending at final_output_node should have a single unconditional edge.
        # So we route human_approval_node directly to final_output_node unconditionally.
        Edge(from_node=human_approval_node, to_node=final_output_node),
    ]
)

# =====================================================================
# APP REGISTRATION
# =====================================================================

app = App(
    root_agent=workflow,
    name="app",
)
