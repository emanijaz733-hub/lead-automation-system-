"""
Minimal SQLite persistence. Swap for Postgres later (same pattern as NEXUS)
if this needs to run for more than one user at a time.
"""
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "crm.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY,
            name TEXT, contact TEXT, source TEXT,
            vehicle_interest TEXT, budget_hint TEXT, timeline TEXT, message TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            lead_id INTEGER PRIMARY KEY,
            score INTEGER, classification TEXT, pipeline_stage TEXT,
            reasoning_log TEXT, followup_draft TEXT, needs_human_review INTEGER,
            approved INTEGER DEFAULT 0
        )
    """)
    # Migration: older databases (created before color/special_features existed)
    # won't have these columns yet. Add them if missing -- safe to run every startup.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
    if "color" not in existing_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN color TEXT")
    if "special_features" not in existing_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN special_features TEXT")
    conn.commit()
    conn.close()


def save_lead(lead: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO leads (id,name,contact,source,vehicle_interest,color,special_features,budget_hint,timeline,message,created_at) "
        "VALUES (:id,:name,:contact,:source,:vehicle_interest,:color,:special_features,:budget_hint,:timeline,:message,:created_at)",
        {**lead, "color": lead.get("color"), "special_features": lead.get("special_features"),
         "created_at": lead.get("created_at", "")}
    )
    conn.commit()
    conn.close()


def create_lead(lead: dict) -> int:
    """
    For a single REAL lead coming in from the public form -- unlike save_lead
    (used for bulk synthetic seeding with pre-assigned ids), this lets SQLite
    auto-assign the id and returns it so the caller can run the agent on it.
    """
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO leads (name,contact,source,vehicle_interest,color,special_features,budget_hint,timeline,message,created_at) "
        "VALUES (:name,:contact,:source,:vehicle_interest,:color,:special_features,:budget_hint,:timeline,:message,:created_at)",
        {**lead, "created_at": lead.get("created_at", "")}
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def normalize_contact(contact: str) -> str:
    """
    Turn a contact string into something comparable across formats, so
    "0321-9876543", "0321 9876543" and "+92 321 9876543" are recognized as
    the same person. Emails are just lowercased; phone numbers are reduced
    to their last 10 digits (drops leading 0 / country code variations).
    Returns "" for junk/blank contacts so those never falsely "match" each other.
    """
    if not contact:
        return ""
    contact = contact.strip()
    if "@" in contact:
        return contact.lower()
    digits = "".join(ch for ch in contact if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def find_duplicate_lead(contact: str):
    """Look for an existing lead from the same person, so a repeat inquiry
    doesn't create a brand new disconnected lead."""
    target = normalize_contact(contact)
    if not target:
        return None
    conn = get_conn()
    rows = conn.execute("SELECT * FROM leads").fetchall()
    conn.close()
    for row in rows:
        if normalize_contact(row["contact"]) == target:
            return dict(row)
    return None


def merge_into_lead(existing_id: int, new_data: dict) -> dict:
    """
    Merge a repeat submission into the existing lead instead of creating a
    duplicate. New info wins where given; nothing is silently lost -- the
    old message is kept as a trail rather than overwritten.
    """
    conn = get_conn()
    existing = dict(conn.execute("SELECT * FROM leads WHERE id=?", (existing_id,)).fetchone())

    combined_message = (new_data.get("message") or "").strip()
    if existing.get("message"):
        earlier = f"[Earlier inquiry: {existing['message']}]"
        combined_message = f"{combined_message}\n\n{earlier}".strip()

    merged = {
        "vehicle_interest": new_data.get("vehicle_interest") or existing.get("vehicle_interest"),
        "color": new_data.get("color") or existing.get("color"),
        "special_features": new_data.get("special_features") or existing.get("special_features"),
        "budget_hint": new_data.get("budget_hint") or existing.get("budget_hint"),
        "timeline": new_data.get("timeline") or existing.get("timeline"),
        "message": combined_message or None,
    }
    conn.execute(
        "UPDATE leads SET vehicle_interest=:vehicle_interest, color=:color, "
        "special_features=:special_features, budget_hint=:budget_hint, "
        "timeline=:timeline, message=:message WHERE id=:id",
        {**merged, "id": existing_id}
    )
    conn.commit()
    conn.close()
    return merged


def save_result(lead_id: int, result: dict):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO results (lead_id,score,classification,pipeline_stage,reasoning_log,followup_draft,needs_human_review,approved) "
        "VALUES (?,?,?,?,?,?,?,COALESCE((SELECT approved FROM results WHERE lead_id=?),0))",
        (lead_id, result.get("score"), result["classification"], result["pipeline_stage"],
         json.dumps(result["reasoning_log"]), result.get("followup_draft"),
         int(result.get("needs_human_review", False)), lead_id)
    )
    conn.commit()
    conn.close()


def get_all():
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.*, r.score, r.classification, r.pipeline_stage, r.reasoning_log,
               r.followup_draft, r.needs_human_review, r.approved
        FROM leads l LEFT JOIN results r ON l.id = r.lead_id
        ORDER BY r.score DESC NULLS LAST
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_followup(lead_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE results SET approved=1, pipeline_stage='Contacted' WHERE lead_id=?",
        (lead_id,)
    )
    conn.commit()
    conn.close()
