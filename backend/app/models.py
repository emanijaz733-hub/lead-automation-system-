"""
Data models for the Honda CRM lead automation system.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Lead(BaseModel):
    id: Optional[int] = None
    name: str
    contact: str  # phone or email
    source: str  # "Facebook Ads", "Website Form", "Walk-in"
    vehicle_interest: Optional[str] = None  # e.g. "Honda Civic RS"
    color: Optional[str] = None  # e.g. "Meteor Grey"
    special_features: Optional[str] = None  # e.g. "sunroof, leather seats"
    budget_hint: Optional[str] = None  # free text, e.g. "around 6.5M"
    timeline: Optional[str] = None  # e.g. "this month", "just browsing"
    message: Optional[str] = None  # raw inquiry text
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ReasoningStep(BaseModel):
    tool_called: str
    input_summary: str
    output_summary: str
    agent_note: str  # why the agent decided to call this tool / what it concluded


class LeadResult(BaseModel):
    lead_id: int
    score: Optional[int] = None  # 0-100, None if not scored
    classification: str  # "Hot" | "Warm" | "Cold" | "Needs Info" | "Spam"
    pipeline_stage: str = "New"  # New -> Contacted -> Qualified -> Proposal -> Won/Lost
    reasoning_log: List[ReasoningStep] = []
    followup_draft: Optional[str] = None
    needs_human_review: bool = False
