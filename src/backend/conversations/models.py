"""
Conversation models for the DocuChat system.
"""
import uuid

from django.db import models
from django.utils import timezone

from documents.models import Document
from users.models import User


class Conversation(models.Model):
    """
    Conversation model for Q&A sessions about documents.

    ``document`` is nullable to support Global RAG conversations that are not
    tied to any specific user-uploaded document.

    ``mode`` determines the conversation type: local_rag (document chat),
    global_rag (legal research), strategist (interactive case analysis),
    or action_engine (legal roadmap and document drafting).
    """
    MODE_CHOICES = [
        ("local_rag", "Local RAG"),
        ("global_rag", "Global RAG / Legal Research"),
        ("strategist", "Interactive Strategist"),
        ("action_engine", "Action Engine"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name='conversations',
        null=True, blank=True,
    )
    title = models.CharField(max_length=500, null=True, blank=True)
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default="global_rag",
        null=True,
        help_text="Conversation mode: local_rag, global_rag, strategist, or action_engine. "
                  "Null defaults to global_rag for backward compatibility.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'conversations'
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['document']),
            models.Index(fields=['updated_at']),
            models.Index(fields=['mode']),
        ]
    
    def __str__(self):
        if self.document:
            return f"Conversation about {self.document.title} ({self.user.email})"
        return f"Global RAG Conversation ({self.user.email})"


class CaseProfile(models.Model):
    """
    Structured facts extracted from a strategist conversation.

    Stores the case type, extracted facts, and completeness score
    as the LLM-driven interview progresses.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="case_profile"
    )
    case_type = models.CharField(
        max_length=100,
        help_text="e.g., contract_dispute, family_law, criminal",
    )
    facts = models.JSONField(
        default=dict,
        help_text="Structured facts: {parties, claims, evidence, timeline, ...}",
    )
    completeness_score = models.FloatField(
        default=0.0,
        help_text="0.0 to 1.0 — how complete the fact profile is",
    )
    is_complete = models.BooleanField(
        default=False,
        help_text="True when enough facts have been gathered for analysis",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'case_profiles'
        indexes = [
            models.Index(fields=['conversation']),
            models.Index(fields=['case_type']),
        ]

    def __str__(self):
        return f"CaseProfile({self.case_type}, score={self.completeness_score})"


class StrategicReport(models.Model):
    """
    Generated strategic analysis report from the Interactive Strategist.

    Contains NEW structured fields from the comprehensive Persian system
    prompt (missing_facts, civil_pathway, criminal_pathway, etc.) plus
    LEGACY fields kept for backward compatibility with existing reports.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="strategic_report"
    )
    case_profile = models.ForeignKey(
        CaseProfile, on_delete=models.CASCADE,
        help_text="The case profile this report was generated from",
    )

    # --- New structured fields (from comprehensive Persian prompt) ---
    missing_facts = models.JSONField(
        default=list, blank=True,
        help_text="List of information gaps identified in the case",
    )
    civil_pathway = models.TextField(
        blank=True, default="",
        help_text="Complete civil/legal pathway analysis",
    )
    criminal_pathway = models.TextField(
        blank=True, default="",
        help_text="Complete criminal pathway analysis",
    )
    pathways_relation = models.TextField(
        blank=True, default="",
        help_text="How civil and criminal pathways interact",
    )
    risk_assessment = models.JSONField(
        default=dict, blank=True,
        help_text="{strengths, weaknesses, success_probability}",
    )
    strategic_recommendation = models.TextField(
        blank=True, default="",
        help_text="Recommended next action",
    )
    sources_used = models.JSONField(
        default=list, blank=True,
        help_text="List of source citations used in the analysis",
    )

    # --- Legacy fields (kept for backward compatibility) ---
    success_probability = models.FloatField(
        help_text="0.0 to 1.0 — estimated likelihood of success",
    )
    summary = models.TextField()
    strengths = models.JSONField(default=list)
    weaknesses = models.JSONField(default=list)
    risks = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    applicable_laws = models.JSONField(
        default=list,
        help_text="[{title, articles, citations}]",
    )
    applicable_precedents = models.JSONField(
        default=list,
        help_text="[{title, number, summary}]",
    )
    raw_report = models.TextField(
        help_text="Full Persian markdown report",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'strategic_reports'
        indexes = [
            models.Index(fields=['conversation']),
            models.Index(fields=['case_profile']),
        ]

    def __str__(self):
        return f"StrategicReport(prob={self.success_probability})"


class Message(models.Model):
    """
    Message model for conversation messages.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list)  # Array of source chunks used
    token_usage = models.JSONField(null=True, blank=True)  # Token usage stats
    hub_metadata = models.JSONField(
        null=True, blank=True, default=None,
        help_text="Metadata for Global RAG queries: stores per-hub results, "
                  "sub-queries, and hub-level token usage.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'messages'
        indexes = [
            models.Index(fields=['conversation']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."