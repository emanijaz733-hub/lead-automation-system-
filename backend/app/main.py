from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import urllib.request

from . import database, data_gen
from .agent import LeadScoringAgent
from .models import Lead

app = FastAPI(title="Honda CRM — Lead Automation")

# n8n integration point: set this to your n8n Webhook node's URL and every
# approved followup gets POSTed there automatically -- n8n then takes it from
# there (send email/SMS, post to Slack, log to a sheet, whatever you wire up).
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")


def notify_n8n(payload: dict):
    if not N8N_WEBHOOK_URL:
        return  # no-op until a real n8n webhook URL is configured
    try:
        req = urllib.request.Request(
            N8N_WEBHOOK_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"n8n webhook call failed (non-fatal): {e}")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

database.init_db()
agent = LeadScoringAgent(past_leads=data_gen.PAST_LEADS_WITH_OUTCOMES)


@app.post("/api/seed")
def seed(n: int = 40):
    """Generate a fresh synthetic batch and run the agent over all of them."""
    leads = data_gen.generate_leads(n)
    for l in leads:
        database.save_lead(l)
        lead_obj = Lead(**l)
        result = agent.run(lead_obj)
        database.save_result(l["id"], result.model_dump())
    return {"seeded": len(leads)}


@app.get("/api/leads")
def list_leads():
    return database.get_all()


@app.post("/api/leads/submit")
def submit_lead(lead: Lead):
    """
    The REAL entry point -- this is what the public lead-capture form (a
    customer filling out name/vehicle/color/etc.) actually posts to. Unlike
    /api/seed (bulk fake data for testing), this takes ONE real submission.

    Before creating anything new, checks whether this contact already has a
    lead on file -- the same person reaching out twice (website today,
    WhatsApp next week) should update ONE lead, not create two disconnected
    ones the sales team has to notice are the same person by hand.
    """
    lead_dict = lead.model_dump(exclude={"id"})

    duplicate = database.find_duplicate_lead(lead_dict["contact"])
    if duplicate:
        merged = database.merge_into_lead(duplicate["id"], lead_dict)
        lead_obj = Lead(
            id=duplicate["id"], name=duplicate["name"], contact=duplicate["contact"],
            source=duplicate["source"], created_at=duplicate["created_at"], **merged,
        )
        result = agent.run(lead_obj)
        database.save_result(duplicate["id"], result.model_dump())
        return {"received": True, "lead_id": duplicate["id"], "duplicate": True,
                "classification": result.classification}

    new_id = database.create_lead(lead_dict)
    lead_obj = Lead(id=new_id, **lead_dict)
    result = agent.run(lead_obj)
    database.save_result(new_id, result.model_dump())
    return {"received": True, "lead_id": new_id, "duplicate": False,
            "classification": result.classification}


@app.post("/api/leads/{lead_id}/rescore")
def rescore(lead_id: int):
    conn = database.get_conn()
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Lead not found")
    lead_obj = Lead(**dict(row))
    result = agent.run(lead_obj)
    database.save_result(lead_id, result.model_dump())
    return result


@app.post("/api/leads/{lead_id}/approve")
def approve(lead_id: int):
    database.approve_followup(lead_id)

    conn = database.get_conn()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    result = conn.execute("SELECT * FROM results WHERE lead_id=?", (lead_id,)).fetchone()
    conn.close()

    # Hand off to n8n (no-op if N8N_WEBHOOK_URL isn't set) -- this is the
    # automation trigger point: n8n receives this and handles actually
    # sending it out, notifying Slack, logging it, etc.
    notify_n8n({
        "lead_id": lead_id,
        "name": lead["name"] if lead else None,
        "contact": lead["contact"] if lead else None,
        "classification": result["classification"] if result else None,
        "message": result["followup_draft"] if result else None,
    })
    return {"approved": lead_id, "n8n_notified": bool(N8N_WEBHOOK_URL)}


@app.get("/api/summary")
def summary():
    rows = database.get_all()
    total = len(rows)
    hot = sum(1 for r in rows if r.get("classification") == "Hot")
    warm = sum(1 for r in rows if r.get("classification") == "Warm")
    needs_info = sum(1 for r in rows if r.get("classification") == "Needs Info")
    pending_review = sum(1 for r in rows if r.get("needs_human_review") and not r.get("approved"))
    return {
        "total": total, "hot": hot, "warm": warm,
        "needs_info": needs_info, "pending_review": pending_review,
    }
