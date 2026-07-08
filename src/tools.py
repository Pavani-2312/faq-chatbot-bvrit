"""
tools.py
--------
Function calling tools for the BVRIT FAQ Chatbot.

Two tools provided:
  1. fee_calculator  — computes total fees for a BVRIT student given branch,
                       batch year, scholarship %, and number of years.
  2. date_checker    — checks whether a BVRIT deadline/event has passed
                       relative to today's date.

These tools handle queries that pure document retrieval cannot answer well:
  - Fee calculations across multiple years with scholarships applied
  - Real-time deadline comparisons ("has the deadline passed?")

Integration:
  The chatbot (chatbot.py) sends tool definitions to the LLM and executes
  whichever tool the model decides to call.

Tool design notes (from HandsOn_FunctionCalling_Questions.docx):
  - Descriptions are BVRIT-specific so the model calls them at the right time.
  - Generic descriptions (e.g. "do math") cause the model to mis-route queries.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Fee data table (from kb_formatted/admission_fee_details.md)
# Per-year fees by batch admission year and branch
# ---------------------------------------------------------------------------

# Tuition fee per year by admission batch
_TUITION_FEES: dict[int, dict[str, int]] = {
    2025: {"cse": 120000, "ece": 120000, "eee": 120000, "it": 120000, "cse-aiml": 120000, "csm": 120000},
    2024: {"cse": 120000, "ece": 120000, "eee": 120000, "it": 120000, "cse-aiml": 120000, "csm": 120000},
    2023: {"cse": 120000, "ece": 120000, "eee": 120000, "it": 120000, "cse-aiml": 120000, "csm": 120000},
    2022: {"cse": 120000, "ece": 120000, "eee": 120000, "it": 120000, "cse-aiml": 120000, "csm": 120000},
    2021: {"cse": 90000,  "ece": 90000,  "eee": 90000,  "it": 90000,  "cse-aiml": 90000,  "csm": 90000},
    2020: {"cse": 90000,  "ece": 90000,  "eee": 90000,  "it": 90000,  "cse-aiml": 90000,  "csm": 90000},
}

# NBA fee per year (not all branches have it)
_NBA_FEES: dict[int, dict[str, int]] = {
    2025: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
    2024: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
    2023: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
    2022: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
    2021: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
    2020: {"cse": 3000, "ece": 3000, "eee": 3000, "it": 3000, "cse-aiml": 0, "csm": 0},
}

# JNTUH / Miscellaneous fee
_JNTUH_FEES: dict[int, int] = {
    2025: 5500, 2024: 5500, 2023: 5500, 2022: 2500, 2021: 5500, 2020: 5500,
}

# Hostel fee per year (per bvrit_college_info.docx — not in KB markdown)
# Using the values from the references document
_HOSTEL_FEE_PER_YEAR = 80000   # approximate; 3-seater room + vegetarian mess ≈ ₹80,000/yr

# Branch name normaliser
_BRANCH_ALIASES: dict[str, str] = {
    "cse": "cse",
    "computer science": "cse",
    "computer science and engineering": "cse",
    "ece": "ece",
    "electronics": "ece",
    "electronics and communication": "ece",
    "electronics and communication engineering": "ece",
    "eee": "eee",
    "electrical": "eee",
    "electrical and electronics": "eee",
    "electrical and electronics engineering": "eee",
    "it": "it",
    "information technology": "it",
    "cse-aiml": "cse-aiml",
    "csm": "cse-aiml",
    "ai&ml": "cse-aiml",
    "aiml": "cse-aiml",
    "cse ai&ml": "cse-aiml",
    "cse artificial intelligence": "cse-aiml",
    "cse (ai&ml)": "cse-aiml",
    "artificial intelligence and machine learning": "cse-aiml",
}

# Display names
_BRANCH_DISPLAY: dict[str, str] = {
    "cse": "Computer Science & Engineering (CSE)",
    "ece": "Electronics & Communication Engineering (ECE)",
    "eee": "Electrical & Electronics Engineering (EEE)",
    "it": "Information Technology (IT)",
    "cse-aiml": "CSE Artificial Intelligence & Machine Learning (CSE AI&ML)",
}


# ---------------------------------------------------------------------------
# OpenAI-format tool definitions (sent in the API call)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "fee_calculator",
            "description": (
                "Calculate the total fees for a BVRIT HYDERABAD student. "
                "Use this tool when the user asks: total 4-year cost, fee with a scholarship "
                "applied, cost per year for a specific branch, or any arithmetic involving "
                "BVRIT tuition/hostel fees that cannot be answered directly from a document. "
                "Do NOT use this for simple lookups like 'what is the CSE tuition fee?' "
                "(use document retrieval for that). Use this when computation is needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": (
                            "The B.Tech branch at BVRIT. One of: CSE, ECE, EEE, IT, CSE-AIML. "
                            "Case-insensitive."
                        ),
                    },
                    "batch_year": {
                        "type": "integer",
                        "description": (
                            "The year the student was admitted (e.g., 2024). "
                            "Used to look up the correct fee table."
                        ),
                    },
                    "years": {
                        "type": "integer",
                        "description": (
                            "Number of years to calculate fees for (1-4). Default is 4 "
                            "for a full B.Tech programme."
                        ),
                        "default": 4,
                    },
                    "scholarship_percent": {
                        "type": "number",
                        "description": (
                            "Scholarship discount as a percentage of tuition fee (0-100). "
                            "For example, 25 means 25% off the annual tuition. Default is 0."
                        ),
                        "default": 0,
                    },
                    "include_hostel": {
                        "type": "boolean",
                        "description": (
                            "If true, include hostel and mess fees in the total. "
                            "Default is false."
                        ),
                        "default": False,
                    },
                },
                "required": ["branch", "batch_year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "date_checker",
            "description": (
                "Check whether a specific BVRIT deadline, event, or academic date has "
                "passed, is upcoming, or calculate days until/since it — relative to today. "
                "Use this when a student asks: 'Has the admission deadline passed?', "
                "'How many days until classes start?', 'Can I still apply for hostel?'. "
                "Do NOT use this for general questions about BVRIT events "
                "(use document retrieval for those)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "The name of the BVRIT event or deadline being checked.",
                    },
                    "event_date": {
                        "type": "string",
                        "description": (
                            "The event date in ISO format YYYY-MM-DD "
                            "(e.g., '2025-07-31' for 31 July 2025)."
                        ),
                    },
                    "query_type": {
                        "type": "string",
                        "enum": ["has_passed", "days_until", "days_since"],
                        "description": (
                            "'has_passed': check if the date is in the past. "
                            "'days_until': how many days until the event. "
                            "'days_since': how many days have passed since the event."
                        ),
                    },
                },
                "required": ["event_name", "event_date", "query_type"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def fee_calculator(
    branch: str,
    batch_year: int,
    years: int = 4,
    scholarship_percent: float = 0,
    include_hostel: bool = False,
) -> dict[str, Any]:
    """
    Compute total fees for a BVRIT student.

    Args:
        branch:              Branch name (case-insensitive).
        batch_year:          Admission year (2020-2025).
        years:               Number of years (1-4).
        scholarship_percent: Tuition discount % (0-100).
        include_hostel:      Include hostel fees.

    Returns:
        dict with breakdown and total.
    """
    # Normalise branch name
    branch_key = _BRANCH_ALIASES.get(branch.lower().strip())
    if not branch_key:
        return {
            "error": f"Unknown branch '{branch}'. Valid branches: CSE, ECE, EEE, IT, CSE-AIML.",
        }

    # Validate batch year
    if batch_year not in _TUITION_FEES:
        available = sorted(_TUITION_FEES.keys())
        return {
            "error": (
                f"Fee data not available for batch year {batch_year}. "
                f"Available years: {available}."
            ),
        }

    # Validate years
    if not 1 <= years <= 4:
        return {"error": f"Years must be between 1 and 4 (given: {years})."}

    # Validate scholarship
    if not 0 <= scholarship_percent <= 100:
        return {"error": f"Scholarship percent must be 0-100 (given: {scholarship_percent})."}

    # Get per-year fees
    annual_tuition = _TUITION_FEES[batch_year].get(branch_key, 0)
    annual_nba = _NBA_FEES[batch_year].get(branch_key, 0)
    annual_jntuh = _JNTUH_FEES.get(batch_year, 5500)

    # Apply scholarship to tuition only
    scholarship_amount = int(annual_tuition * scholarship_percent / 100)
    net_tuition = annual_tuition - scholarship_amount

    # Per-year totals
    per_year_academic = net_tuition + annual_nba + annual_jntuh
    per_year_hostel = _HOSTEL_FEE_PER_YEAR if include_hostel else 0
    per_year_total = per_year_academic + per_year_hostel

    # Multi-year totals
    total_academic = per_year_academic * years
    total_hostel = per_year_hostel * years
    grand_total = per_year_total * years

    branch_display = _BRANCH_DISPLAY.get(branch_key, branch_key.upper())

    return {
        "branch": branch_display,
        "batch_year": batch_year,
        "years_calculated": years,
        "per_year": {
            "tuition_before_scholarship": annual_tuition,
            "scholarship_deduction": scholarship_amount,
            "tuition_after_scholarship": net_tuition,
            "nba_fee": annual_nba,
            "jntuh_misc_fee": annual_jntuh,
            "hostel_fee": per_year_hostel,
            "total_per_year": per_year_total,
        },
        "total": {
            "academic_fees": total_academic,
            "hostel_fees": total_hostel,
            "grand_total": grand_total,
        },
        "scholarship_applied": f"{scholarship_percent}% on tuition",
        "note": (
            "All amounts in Indian Rupees (₹). "
            "Fees sourced from BVRIT fee structure table. "
            "Hostel fee is approximate (~₹80,000/year for standard room + mess). "
            "Verify exact amounts with the college admissions office."
        ),
    }


def date_checker(
    event_name: str,
    event_date: str,
    query_type: str,
) -> dict[str, Any]:
    """
    Check a BVRIT event/deadline date relative to today.

    Args:
        event_name:   Name of the BVRIT event.
        event_date:   ISO date string (YYYY-MM-DD).
        query_type:   'has_passed', 'days_until', or 'days_since'.

    Returns:
        dict with result and explanation.
    """
    # Parse the event date
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "error": f"Invalid date format '{event_date}'. Please use YYYY-MM-DD."
        }

    today = date.today()
    delta = (event_dt - today).days  # positive = future, negative = past

    if query_type == "has_passed":
        has_passed = today >= event_dt
        return {
            "event_name": event_name,
            "event_date": event_date,
            "today": today.isoformat(),
            "has_passed": has_passed,
            "status": (
                f"Yes, the {event_name} date ({event_date}) has already passed. "
                f"It was {abs(delta)} days ago."
                if has_passed else
                f"No, the {event_name} date ({event_date}) has not passed yet. "
                f"It is in {delta} days."
            ),
        }

    elif query_type == "days_until":
        if delta < 0:
            return {
                "event_name": event_name,
                "event_date": event_date,
                "today": today.isoformat(),
                "days_until": 0,
                "status": (
                    f"The {event_name} ({event_date}) has already passed "
                    f"— it was {abs(delta)} days ago."
                ),
            }
        return {
            "event_name": event_name,
            "event_date": event_date,
            "today": today.isoformat(),
            "days_until": delta,
            "status": f"There are {delta} days until {event_name} ({event_date}).",
        }

    elif query_type == "days_since":
        if delta > 0:
            return {
                "event_name": event_name,
                "event_date": event_date,
                "today": today.isoformat(),
                "days_since": 0,
                "status": (
                    f"The {event_name} ({event_date}) has not happened yet "
                    f"— it is in {delta} days."
                ),
            }
        return {
            "event_name": event_name,
            "event_date": event_date,
            "today": today.isoformat(),
            "days_since": abs(delta),
            "status": f"It has been {abs(delta)} days since {event_name} ({event_date}).",
        }

    else:
        return {
            "error": (
                f"Unknown query_type '{query_type}'. "
                "Use: 'has_passed', 'days_until', or 'days_since'."
            )
        }


# ---------------------------------------------------------------------------
# Tool dispatcher — maps tool name to function
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS: dict[str, Any] = {
    "fee_calculator": fee_calculator,
    "date_checker": date_checker,
}


def execute_tool_call(tool_name: str, arguments: dict) -> dict:
    """
    Execute a tool call returned by the LLM.

    Args:
        tool_name:  Name of the tool to call.
        arguments:  Dict of arguments from the LLM tool call.

    Returns:
        Tool result as a dict.
    """
    fn = TOOL_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: '{tool_name}'."}

    # Validate and call
    try:
        result = fn(**arguments)
    except TypeError as e:
        return {"error": f"Invalid arguments for {tool_name}: {e}"}
    except Exception as e:
        return {"error": f"Tool execution error ({tool_name}): {e}"}

    return result


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== fee_calculator tests ===")
    print(json.dumps(fee_calculator("CSE", 2024, years=4), indent=2))
    print()
    print(json.dumps(fee_calculator("CSE", 2024, years=4, scholarship_percent=25, include_hostel=True), indent=2))
    print()
    print(json.dumps(fee_calculator("invalid_branch", 2024), indent=2))
    print()

    print("=== date_checker tests ===")
    print(json.dumps(date_checker("EAMCET Counselling", "2025-07-31", "has_passed"), indent=2))
    print()
    print(json.dumps(date_checker("Orientation Day", "2025-08-01", "days_until"), indent=2))
