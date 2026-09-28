"""
LeadScoringAgent -- the actual agentic component.

Unlike a fixed pipeline, this agent's PATH through the tools differs per
lead: it decides whether completeness checking is even needed, whether a
lead is borderline enough to justify comparing against similar past leads,
and whether to draft a follow-up at all. That branching is what makes this
an agent rather than a script wrapped in AI language.

Runs in RULE_BASED mode by default (no API key needed, fully working now).
To upgrade to real LLM-driven tool selection, set an ANTHROPIC_API_KEY env
var and flip USE_LLM = True below -- the tool functions themselves don't
need to change, only how the agent decides which one to call next.
"""
import os
from typing import List, Dict
from .models import Lead, LeadResult, ReasoningStep
from . import tools

USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))

HOT_THRESHOLD = 70
WARM_THRESHOLD = 45
BORDERLINE_BAND = (WARM_THRESHOLD - 10, WARM_THRESHOLD + 10)  # (35, 55) triggers extra lookup


class LeadScoringAgent:
    def __init__(self, past_leads: List[Dict] = None):
        self.past_leads = past_leads or []

    def run(self, lead: Lead) -> LeadResult:
        log: List[ReasoningStep] = []

        # Step 1: always check for spam first -- cheap, and if a lead is spam
        # the agent skips every other tool entirely. This IS the agentic part:
        # the decision to stop early is made by the agent, not hardcoded per-lead.
        spam = tools.detect_spam(lead)
        log.append(ReasoningStep(
            tool_called="detect_spam",
            input_summary=f"message='{(lead.message or '')[:40]}...'",
            output_summary=str(spam),
            agent_note="Checking for spam signals before investing further effort."
        ))
        if spam["is_spam"]:
            log.append(ReasoningStep(
                tool_called="(decision)",
                input_summary="spam=True",
                output_summary="stopping here",
                agent_note="Spam signals found -- no point running completeness or scoring. Classifying directly."
            ))
            return LeadResult(
                lead_id=lead.id or 0, score=None, classification="Spam",
                pipeline_stage="Archived", reasoning_log=log, needs_human_review=False,
            )
        # (pipeline stages used for the Kanban board: New, Needs Review,
        # Ready to Contact, Contacted, Archived)

        # Step 2: completeness check
        completeness = tools.check_completeness(lead)
        log.append(ReasoningStep(
            tool_called="check_completeness",
            input_summary=f"lead fields present: contact={bool(lead.contact)}, vehicle={bool(lead.vehicle_interest)}",
            output_summary=str(completeness),
            agent_note="Checking whether there's enough information to score this lead meaningfully."
        ))
        if completeness["missing_critical"]:
            log.append(ReasoningStep(
                tool_called="(decision)",
                input_summary=f"missing={completeness['missing_fields']}",
                output_summary="skipping scoring tool",
                agent_note="Critical fields missing -- scoring would be unreliable. Flagging for human follow-up instead of guessing."
            ))
            return LeadResult(
                lead_id=lead.id or 0, score=None, classification="Needs Info",
                pipeline_stage="Needs Review", reasoning_log=log, needs_human_review=True,
            )

        # Step 3: scoring
        scoring = tools.score_criteria(lead)
        log.append(ReasoningStep(
            tool_called="score_criteria",
            input_summary="all critical fields present",
            output_summary=str(scoring),
            agent_note="Enough information present -- scoring against weighted criteria."
        ))
        score = scoring["weighted_score"]

        # Step 4: ONLY for borderline scores, agent decides to consult similar past leads.
        # This is a real conditional tool call, not something every lead goes through.
        if BORDERLINE_BAND[0] <= score <= BORDERLINE_BAND[1] and self.past_leads:
            similar = tools.lookup_similar_leads(lead, self.past_leads)
            log.append(ReasoningStep(
                tool_called="lookup_similar_leads",
                input_summary=f"score={score} is borderline, checking comparable leads",
                output_summary=str(similar),
                agent_note="Score alone isn't decisive here -- comparing against similar past leads to break the tie."
            ))
            if similar["avg_outcome_score"] is not None:
                score = round((score + similar["avg_outcome_score"]) / 2)
                log.append(ReasoningStep(
                    tool_called="(decision)",
                    input_summary=f"blended with similar-lead outcome {similar['avg_outcome_score']}",
                    output_summary=f"adjusted score={score}",
                    agent_note="Adjusted score based on how similar leads historically performed."
                ))

        classification = "Hot" if score >= HOT_THRESHOLD else ("Warm" if score >= WARM_THRESHOLD else "Cold")

        # Step 5: only Hot/Warm leads get a drafted follow-up -- Cold leads don't
        # waste a tool call on a message nobody asked for.
        followup = None
        needs_review = False
        if classification in ("Hot", "Warm"):
            followup = tools.draft_followup(lead, classification)
            needs_review = True  # human always approves outbound messages
            log.append(ReasoningStep(
                tool_called="draft_followup",
                input_summary=f"classification={classification}",
                output_summary=followup[:60] + "...",
                agent_note="Lead is worth pursuing -- drafting outreach for a human to review and send."
            ))
        else:
            log.append(ReasoningStep(
                tool_called="(decision)",
                input_summary=f"classification={classification}",
                output_summary="no followup drafted",
                agent_note="Score too low to justify outreach right now."
            ))

        stage = "Ready to Contact" if classification in ("Hot", "Warm") else "Archived"
        return LeadResult(
            lead_id=lead.id or 0,
            score=score,
            classification=classification,
            pipeline_stage=stage,
            reasoning_log=log,
            followup_draft=followup,
            needs_human_review=needs_review,
        )
