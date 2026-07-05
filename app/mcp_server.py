# ruff: noqa
import sys
import logging
from typing import List, Dict, Any
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr because stdio transport uses stdout for JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("elderly_care_mcp_server")

# Initialize FastMCP Server
mcp = FastMCP("elderly-care-server")

# In-memory database for local persistence during session
db = {
    "medications": [
        {"id": 1, "name": "Lisinopril", "dosage": "10mg", "frequency": "Daily at 8:00 AM", "purpose": "Blood Pressure"},
        {"id": 2, "name": "Metformin", "dosage": "500mg", "frequency": "Twice daily with meals", "purpose": "Diabetes"},
        {"id": 3, "name": "Atorvastatin", "dosage": "20mg", "frequency": "Daily at bedtime", "purpose": "Cholesterol"},
    ],
    "medication_logs": [
        {"timestamp": "2026-07-05 08:15 AM", "medication": "Lisinopril", "status": "Taken"},
        {"timestamp": "2026-07-05 08:30 AM", "medication": "Metformin", "status": "Taken"},
    ],
    "wellbeing_logs": [
        {"timestamp": "2026-07-04 09:00 PM", "mood": "Cheerful", "pain_level": "2/10", "sleep_hours": 7.5, "notes": "Felt good, went for a short walk."},
    ],
    "doctor_visits": [
        {"id": 1, "date": "2026-07-12 10:00 AM", "doctor": "Dr. Sarah Patel (Cardiologist)", "location": "St. Jude Clinic Suite 400", "notes": "Routine blood pressure checkup."},
        {"id": 2, "date": "2026-07-28 02:30 PM", "doctor": "Dr. James Miller (GP)", "location": "Community Health Center", "notes": "Annual physical and blood work review."},
    ]
}

@mcp.tool()
def get_medications() -> str:
    """
    Retrieve the list of current medications for the elderly patient.
    """
    logger.info("MCP: Retrieving medications list.")
    lines = []
    for med in db["medications"]:
        lines.append(f"- ID {med['id']}: {med['name']} ({med['dosage']}) - {med['frequency']} [For: {med['purpose']}]")
    return "\n".join(lines) if lines else "No medications listed."

@mcp.tool()
def log_medication_dose(medication_name: str, status: str = "Taken", timestamp: str = "Just now") -> str:
    """
    Log a dose of medication as taken or missed.
    
    Args:
        medication_name: Name of the medication.
        status: Status (e.g. 'Taken', 'Missed', 'Refused').
        timestamp: Time of the log.
    """
    logger.info(f"MCP: Logging dose for {medication_name} as {status}.")
    log_entry = {
        "timestamp": timestamp,
        "medication": medication_name,
        "status": status
    }
    db["medication_logs"].append(log_entry)
    return f"Successfully logged: {medication_name} dosage marked as '{status}' at {timestamp}."

@mcp.tool()
def get_medication_logs() -> str:
    """
    Retrieve the historical log of administered medications.
    """
    logger.info("MCP: Retrieving medication logs.")
    lines = []
    for log in db["medication_logs"]:
        lines.append(f"[{log['timestamp']}] {log['medication']}: {log['status']}")
    return "\n".join(lines) if lines else "No medication logs found."

@mcp.tool()
def get_wellbeing_history() -> str:
    """
    Retrieve the historical log of patient well-being check-ins.
    """
    logger.info("MCP: Retrieving well-being history.")
    lines = []
    for log in db["wellbeing_logs"]:
        lines.append(
            f"[{log['timestamp']}] Mood: {log['mood']} | Pain: {log['pain_level']} | "
            f"Sleep: {log['sleep_hours']} hours | Notes: {log['notes']}"
        )
    return "\n".join(lines) if lines else "No well-being logs found."

@mcp.tool()
def log_wellbeing(mood: str, pain_level: str, sleep_hours: float, notes: str, timestamp: str = "Just now") -> str:
    """
    Add a daily well-being check-in log for the patient.
    
    Args:
        mood: Overall emotional status (e.g. 'Happy', 'Anxious', 'Tired', 'Cheerful').
        pain_level: Level of pain (e.g. '1/10', 'None', 'Moderate').
        sleep_hours: Hours of sleep last night.
        notes: General physical state notes or remarks.
        timestamp: Time of the log.
    """
    logger.info(f"MCP: Logging well-being: mood={mood}, pain={pain_level}.")
    log_entry = {
        "timestamp": timestamp,
        "mood": mood,
        "pain_level": pain_level,
        "sleep_hours": sleep_hours,
        "notes": notes
    }
    db["wellbeing_logs"].append(log_entry)
    return f"Successfully logged well-being status: Mood: {mood}, Pain: {pain_level}, Sleep: {sleep_hours}h."

@mcp.tool()
def get_doctor_visits() -> str:
    """
    Retrieve upcoming doctor visits and appointments.
    """
    logger.info("MCP: Retrieving doctor visits.")
    lines = []
    for visit in db["doctor_visits"]:
        lines.append(
            f"- Date: {visit['date']} | Dr: {visit['doctor']} | "
            f"Location: {visit['location']} | Notes: {visit['notes']}"
        )
    return "\n".join(lines) if lines else "No doctor visits scheduled."

if __name__ == "__main__":
    mcp.run()
