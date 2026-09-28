"""
Tools available to the lead-scoring agent.

Each tool is a plain function with a clear input/output contract. The agent
(see agent.py) decides WHICH of these to call, and in what order, based on
what it observes about each lead -- that decision logic is what makes this
agentic rather than a fixed pipeline.

Placeholder scoring weights below are NOT Honda's real criteria (those are
still unconfirmed). Swap CRITERIA_WEIGHTS once real criteria are provided.
"""
from typing import Dict, List
from .models import Lead

# ---- Placeholder criteria (swap with Honda's real weights once confirmed) ----
CRITERIA_WEIGHTS = {
    "timeline_urgency": 0.35,
    "budget_clarity": 0.25,
    "vehicle_specificity": 0.25,
    "message_intent": 0.15,
}

URGENT_TIMELINE_TERMS = ["this week", "this month", "asap", "urgent", "today", "tomorrow"]
VAGUE_TIMELINE_TERMS = ["just browsing", "not sure", "someday", "later", "no rush"]
SPAM_SIGNALS = ["http://", "https://", "www.", "click here", "free money", "guaranteed"]


def check_completeness(lead: Lead) -> Dict:
    """Tool: identify missing critical fields on a lead."""
    missing = []
    if not lead.contact or len(lead.contact.strip()) < 5:
        missing.append("contact")
    if not lead.vehicle_interest:
        missing.append("vehicle_interest")
    if not lead.timeline:
        missing.append("timeline")
    if not lead.message or len(lead.message.strip()) < 5:
        missing.append("message")

    critical_missing = "contact" in missing or ("vehicle_interest" in missing and "message" in missing)
    return {
        "missing_fields": missing,
        "missing_critical": critical_missing,
    }


def detect_spam(lead: Lead) -> Dict:
    """Tool: flag likely spam/junk leads before wasting scoring effort on them."""
    text = f"{lead.message or ''} {lead.vehicle_interest or ''}".lower()
    hits = [s for s in SPAM_SIGNALS if s in text]
    is_spam = len(hits) > 0
    return {"is_spam": is_spam, "signals": hits}


def score_criteria(lead: Lead) -> Dict:
    """Tool: score a lead 0-100 against weighted criteria."""
    scores = {}

    timeline = (lead.timeline or "").lower()
    if any(t in timeline for t in URGENT_TIMELINE_TERMS):
        scores["timeline_urgency"] = 90
    elif any(t in timeline for t in VAGUE_TIMELINE_TERMS):
        scores["timeline_urgency"] = 20
    elif timeline:
        scores["timeline_urgency"] = 55
    else:
        scores["timeline_urgency"] = 10

    budget = (lead.budget_hint or "").strip()
    if budget and any(ch.isdigit() for ch in budget):
        scores["budget_clarity"] = 85
    elif budget:
        scores["budget_clarity"] = 40
    else:
        scores["budget_clarity"] = 15

    vehicle = (lead.vehicle_interest or "").strip()
    scores["vehicle_specificity"] = 85 if len(vehicle.split()) >= 2 else (40 if vehicle else 10)

    msg = (lead.message or "").lower()
    intent_terms = ["price", "test drive", "available", "book", "visit", "installment", "finance"]
    scores["message_intent"] = min(95, 30 + 15 * sum(1 for t in intent_terms if t in msg))

    weighted = sum(scores[k] * CRITERIA_WEIGHTS[k] for k in CRITERIA_WEIGHTS)
    return {"criteria_scores": scores, "weighted_score": round(weighted)}


def lookup_similar_leads(lead: Lead, past_leads: List[Dict]) -> Dict:
    """
    Tool: compare a borderline lead against a small set of past (synthetic)
    leads to see whether similar profiles tended to convert. Only called
    by the agent for genuinely ambiguous cases, not every lead.
    """
    if not past_leads:
        return {"similar_found": 0, "avg_outcome_score": None}

    vehicle = (lead.vehicle_interest or "").lower()
    matches = [p for p in past_leads if vehicle and vehicle.split()[0] in (p.get("vehicle_interest") or "").lower()]
    if not matches:
        return {"similar_found": 0, "avg_outcome_score": None}

    avg = sum(p.get("outcome_score", 50) for p in matches) / len(matches)
    return {"similar_found": len(matches), "avg_outcome_score": round(avg)}


def draft_followup(lead: Lead, classification: str) -> str:
    """
    Tool: draft an outreach message tailored to the lead. Human reviews before sending.

    Uses a real LLM call if an API key is set (genuinely tailored per lead,
    reads their actual message/context). Falls back to a template if no key
    is present, so the app works end-to-end either way. Tries GROK_API_KEY,
    then GEMINI_API_KEY, then ANTHROPIC_API_KEY, in that order.
    """
    import os
    grok_key = os.environ.get("GROK_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if grok_key:
        try:
            return _draft_followup_grok(lead, classification, grok_key)
        except Exception as e:
            print(f"[LLM] Grok call failed: {e}")
    if gemini_key:
        try:
            return _draft_followup_gemini(lead, classification, gemini_key)
        except Exception as e:
            print(f"[LLM] Gemini call failed: {e}")
    if anthropic_key:
        try:
            return _draft_followup_llm(lead, classification, anthropic_key)
        except Exception as e:
            print(f"[LLM] Anthropic call failed: {e}")

    vehicle = lead.vehicle_interest or "one of our vehicles"
    if lead.color:
        vehicle += f" in {lead.color}"
    name = lead.name.split()[0] if lead.name else "there"
    features_note = f" with {lead.special_features}" if lead.special_features else ""

    if classification == "Hot":
        return (
            f"Hi {name}, thanks for your interest in the {vehicle}{features_note}! "
            f"I'd love to get you behind the wheel this week -- are you free for a quick test drive? "
            f"Happy to also share current pricing and financing options."
        )
    else:  # Warm
        return (
            f"Hi {name}, thanks for reaching out about the {vehicle}{features_note}. "
            f"Whenever you're ready, I'm happy to answer any questions or set up a time to see it in person -- "
            f"no pressure, just let me know what works for you."
        )


def _followup_prompt(lead: Lead, classification: str) -> str:
    return f"""Write a short, warm sales follow-up message (3-4 sentences max) from a Honda
dealership salesperson to this lead. Sound human, not corporate. Reference their
specific interest naturally. Don't be pushy.

Lead name: {lead.name}
Vehicle interest: {lead.vehicle_interest or "not specified"}
Color preference: {lead.color or "not specified"}
Special features wanted: {lead.special_features or "none noted"}
Their message: {lead.message or "none provided"}
Timeline: {lead.timeline or "not specified"}
Classification: {classification} lead

Write only the message, nothing else."""


def _draft_followup_grok(lead: Lead, classification: str, api_key: str) -> str:
    """Grok (xAI) drafted message -- OpenAI-compatible API, same pattern used in NEXUS."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    resp = client.chat.completions.create(
        model="grok-4-fast-non-reasoning",
        messages=[{"role": "user", "content": _followup_prompt(lead, classification)}],
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()


def _draft_followup_gemini(lead: Lead, classification: str, api_key: str) -> str:
    """Gemini drafted message -- also OpenAI-compatible via Google's compat endpoint."""
    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = client.chat.completions.create(
        model="gemini-3.6-flash",
        messages=[{"role": "user", "content": _followup_prompt(lead, classification)}],
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()


def _draft_followup_llm(lead: Lead, classification: str, api_key: str) -> str:
    """Real LLM-drafted message -- actually reads the lead's message/context, not a template."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": _followup_prompt(lead, classification)}],
    )
    return resp.content[0].text.strip()
