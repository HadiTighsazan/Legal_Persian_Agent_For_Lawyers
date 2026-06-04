"""
Strategist Service — Interactive Case Analysis Pipeline.

Provides the :class:`StrategistService` class that orchestrates the guided
interview → research → analysis flow for the Interactive Strategist mode.

Pipeline Flow::

    1. receive_case_description(user_input, conversation_history)
       → LLM analyzes input, identifies case type (contract, family, criminal, etc.)
       → Returns structured case profile with known facts and gaps

    2. generate_next_question(case_profile, conversation_history)
       → LLM determines the most important missing fact
       → Returns a targeted question in Persian

    3. check_readiness(case_profile)
       → If enough facts gathered → proceed to analysis
       → If gaps remain → return to step 2

    4. run_strategic_analysis(case_profile)
       → Query all 3 legal hubs via multi_hub_search()
       → LLM analyzes facts against retrieved laws/precedents
       → Generate success probability, risk assessment, recommendations

    5. generate_report(analysis_result)
       → Format as structured Persian report with sections
       → Include citations to specific laws and precedents
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Generator

from django.conf import settings

from conversations.global_rag_service import (
    build_global_context,
    multi_hub_search,
)
from conversations.models import CaseProfile, StrategicReport
from conversations.question_router import (
    HUB_LABELS,
    RouterResult,
    SubQuery,
    route_question,
)
from providers.registry import get_chat_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max tokens for fact extraction LLM calls
_FACT_EXTRACTION_MAX_TOKENS: int = 1024

# Max tokens for question generation LLM calls
_QUESTION_MAX_TOKENS: int = 300

# Max tokens for strategic analysis LLM calls
_ANALYSIS_MAX_TOKENS: int = 8192

# Max tokens for report generation LLM calls
_REPORT_MAX_TOKENS: int = 8192

# Completeness threshold — when score >= this, the case is ready for analysis
_COMPLETENESS_THRESHOLD: float = 0.7

# Number of chunks to retrieve per hub for strategic analysis
_STRATEGY_TOP_K_PER_HUB: int = 5

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class FactExtractionResult:
    """Result of a fact extraction LLM call.

    Attributes:
        case_type: The identified case type (e.g. ``"contract_dispute"``).
        facts: Structured facts dict extracted from the conversation.
        completeness_score: 0.0–1.0 estimate of how complete the profile is.
        missing_facts: List of critical missing fact descriptions.
        next_question: A targeted question in Persian to ask the user next.
        is_ready: Whether enough facts have been gathered for analysis.
    """
    case_type: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    completeness_score: float = 0.0
    missing_facts: list[str] = field(default_factory=list)
    next_question: str = ""
    is_ready: bool = False


@dataclass
class AnalysisResult:
    """Result of the strategic analysis LLM call.

    Attributes:
        success_probability: 0.0–1.0 estimated likelihood of success.
        summary: Brief Persian summary of the analysis.
        strengths: List of case strengths.
        weaknesses: List of case weaknesses.
        risks: List of identified risks.
        recommendations: List of recommended actions.
        applicable_laws: List of ``{title, articles, citations}`` dicts.
        applicable_precedents: List of ``{title, number, summary}`` dicts.
        raw_report: Full Persian markdown report text.
    """
    success_probability: float = 0.0
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    applicable_laws: list[dict[str, Any]] = field(default_factory=list)
    applicable_precedents: list[dict[str, Any]] = field(default_factory=list)
    raw_report: str = ""


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

FACT_EXTRACTION_SYSTEM_PROMPT: str = (
    "You are a Persian legal fact extractor. Your task is to analyse the user's "
    "messages and extract structured case facts for a legal case profile.\n\n"
    "### Instructions:\n"
    "1. Identify the **case type** from these categories:\n"
    "   - ``contract_dispute`` — اختلافات قراردادی\n"
    "   - ``family_law`` — دعاوی خانواده (طلاق، مهریه، نفقه، حضانت)\n"
    "   - ``criminal`` — دعاوی کیفری\n"
    "   - ``civil`` — دعاوی حقوقی (ملکی، چک، سفته)\n"
    "   - ``labour`` — دعاوی کار و کارگری\n"
    "   - ``inheritance`` — دعاوی ارث\n"
    "   - ``property`` — دعاوی ملکی و املاک\n"
    "   - ``other`` — سایر\n\n"
    "2. Extract structured **facts** into a JSON object. Include ALL known facts:\n"
    "   - ``parties``: Who are the parties involved? (plaintiff, defendant)\n"
    "   - ``claims``: What are the claims or demands?\n"
    "   - ``evidence``: What evidence exists? (documents, witnesses, etc.)\n"
    "   - ``timeline``: Key dates and events\n"
    "   - ``amount``: Monetary amounts if applicable\n"
    "   - ``jurisdiction``: Court or jurisdiction if mentioned\n"
    "   - ``current_status``: Current status of the case\n"
    "   - Any other relevant fields\n\n"
    "3. Estimate **completeness_score** (0.0–1.0):\n"
    "   - 0.0–0.3: Only initial description, most facts unknown\n"
    "   - 0.3–0.6: Some facts known, critical gaps remain\n"
    "   - 0.6–0.8: Most key facts gathered, minor gaps\n"
    "   - 0.8–1.0: Comprehensive fact profile ready for analysis\n\n"
    "4. List **missing_facts**: What critical information is still needed?\n"
    "   - Be specific about what's missing (e.g., \"مبلغ دقیق خواسته\", "
    "\"تاریخ انعقاد قرارداد\")\n\n"
    "5. Generate a **next_question** in Persian: A single, targeted question "
    "asking for the most important missing fact.\n\n"
    "6. Set **is_ready**: ``true`` if completeness_score >= 0.7, else ``false``.\n\n"
    "### Output Format:\n"
    "Respond ONLY with valid JSON:\n"
    "```json\n"
    "{\n"
    '  "case_type": "contract_dispute",\n'
    '  "facts": {"parties": {...}, "claims": "...", ...},\n'
    '  "completeness_score": 0.6,\n'
    '  "missing_facts": ["تاریخ انعقاد قرارداد مشخص نیست", ...],\n'
    '  "next_question": "لطفاً تاریخ دقیق انعقاد قرارداد را ذکر کنید.",\n'
    '  "is_ready": false\n'
    "}\n"
    "```\n\n"
    "### Important:\n"
    "- Preserve ALL Persian text exactly as written by the user.\n"
    "- If the user provides new information, merge it with existing facts "
    "(do not discard previously extracted facts).\n"
    "- Be conservative with completeness_score — only mark as ready when "
    "you have enough for a meaningful legal analysis."
)

COMPLETENESS_CHECKER_PROMPT: str = (
    "You are a Persian legal completeness checker. Your task is to evaluate "
    "whether enough facts have been gathered for a strategic legal analysis.\n\n"
    "### Instructions:\n"
    "1. Review the case type and extracted facts below.\n"
    "2. For the identified case type, determine which facts are **critical** "
    "for a meaningful legal analysis.\n"
    "3. Score completeness from 0.0 to 1.0.\n"
    "4. If completeness >= 0.7, set ``is_ready`` to ``true``.\n"
    "5. If not ready, generate a single targeted **next_question** in Persian "
    "asking for the most important missing fact.\n\n"
    "### Critical Facts by Case Type:\n"
    "- **contract_dispute**: parties, contract date, subject matter, breach "
    "description, claimed damages, evidence\n"
    "- **family_law**: parties (husband/wife), marriage date, type of claim "
    "(divorce/dowry/alimony/custody), children, evidence\n"
    "- **criminal**: accused, victim, crime description, date/location of "
    "incident, evidence, current status (complaint filed?)\n"
    "- **civil**: parties, subject of claim, amount, documents, timeline\n"
    "- **labour**: employee, employer, contract type, termination reason, "
    "claims, evidence\n"
    "- **inheritance**: deceased, heirs, estate description, will status, "
    "dispute description\n"
    "- **property**: property description, parties, ownership documents, "
    "dispute nature\n\n"
    "### Output Format:\n"
    "Respond ONLY with valid JSON:\n"
    "```json\n"
    "{\n"
    '  "completeness_score": 0.5,\n'
    '  "missing_facts": ["تاریخ قرارداد مشخص نیست"],\n'
    '  "next_question": "لطفاً تاریخ دقیق قرارداد را بفرمایید.",\n'
    '  "is_ready": false\n'
    "}\n"
    "```"
)

STRATEGIC_ANALYSIS_SYSTEM_PROMPT: str = (
    "You are a senior Persian legal strategist (حقوقدان و استراتژیست حقوقی). "
    "Your task is to analyse a legal case based on the provided facts and "
    "retrieved legal context, then produce a comprehensive strategic report "
    "in Persian.\n\n"
    "### Instructions:\n"
    "1. Analyse the **case facts** against the **applicable laws** and "
    "**judicial precedents** provided in the context.\n"
    "2. Estimate **success_probability** (0.0–1.0) based on:\n"
    "   - Strength of legal arguments given the facts\n"
    "   - Supporting legislation and precedents\n"
    "   - Potential counter-arguments and weaknesses\n\n"
    "3. Identify **strengths**: What aspects of the case are favourable?\n"
    "4. Identify **weaknesses**: What aspects are problematic?\n"
    "5. Identify **risks**: Procedural, evidentiary, or legal risks.\n"
    "6. Provide **recommendations**: Specific, actionable next steps.\n"
    "7. List **applicable_laws**: Specific laws, articles, and codes that "
    "apply to this case. Include article numbers.\n"
    "8. List **applicable_precedents**: Relevant judicial precedents or "
    "advisory opinions from the context.\n\n"
    "### Output Format:\n"
    "Respond with a JSON object containing the structured analysis, PLUS a "
    "``raw_report`` field containing the FULL Persian markdown report.\n\n"
    "```json\n"
    "{\n"
    '  "success_probability": 0.65,\n'
    '  "summary": "خلاصه تحلیل استراتژیک به زبان فارسی...",\n'
    '  "strengths": ["نقطه قوت ۱", "نقطه قوت ۲"],\n'
    '  "weaknesses": ["نقطه ضعف ۱", "نقطه ضعف ۲"],\n'
    '  "risks": ["ریسک ۱", "ریسک ۲"],\n'
    '  "recommendations": ["توصیه ۱", "توصیه ۲"],\n'
    '  "applicable_laws": [\n'
    '    {"title": "قانون مدنی", "articles": "مواد ۱۰ و ۲۱۹", '
    '"citations": "[Source 1]"}\n'
    "  ],\n"
    '  "applicable_precedents": [\n'
    '    {"title": "رأی وحدت رویه", "number": "۷۴۲", '
    '"summary": "خلاصه رأی..."}\n'
    "  ],\n"
    '  "raw_report": "# گزارش تحلیل استراتژیک\\n\\n## خلاصه\\n... (full Persian markdown report)"\n'
    "}\n"
    "```\n\n"
    "### Important:\n"
    "- The **raw_report** must be a complete, well-formatted Persian markdown "
    "report with sections: خلاصه, نقاط قوت, نقاط ضعف, ریسک‌ها, توصیه‌ها, "
    "قوانین مرتبط, رویه‌های قضایی مرتبط.\n"
    "- Cite specific sources using [Source N] notation matching the context.\n"
    "- Be objective and balanced — present both favourable and unfavourable aspects.\n"
    "- Use formal legal Persian throughout."
)

# ---------------------------------------------------------------------------
# FactExtractor
# ---------------------------------------------------------------------------


class FactExtractor:
    """LLM-powered extraction of structured facts from conversation.

    Uses the configured chat provider to analyse user messages and extract
    structured case facts into a :class:`CaseProfile` model.
    """

    def __init__(self) -> None:
        self._provider = get_chat_provider()

    def extract(
        self,
        user_message: str,
        conversation_history: list[dict[str, str]] | None = None,
        existing_profile: dict[str, Any] | None = None,
    ) -> FactExtractionResult:
        """Extract structured facts from a user message.

        Args:
            user_message: The user's latest message text.
            conversation_history: Optional list of prior message dicts with
                ``role`` and ``content`` keys.
            existing_profile: Optional existing facts dict to merge with
                (from a previously saved :class:`CaseProfile`).

        Returns:
            A :class:`FactExtractionResult` with extracted facts and
            completeness assessment.
        """
        # Build the extraction prompt
        prompt_parts: list[str] = ["User message: " + user_message]

        if conversation_history:
            # Include relevant history (last 6 turns for context)
            recent_history = conversation_history[-6:]
            history_text = "\n".join(
                f"{msg['role']}: {msg['content']}"
                for msg in recent_history
            )
            prompt_parts.append("\nConversation history:\n" + history_text)

        if existing_profile:
            prompt_parts.append(
                "\nExisting extracted facts (merge with new info):\n"
                + json.dumps(existing_profile, ensure_ascii=False, indent=2)
            )

        prompt = "\n---\n".join(prompt_parts)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info(
            "FactExtractor.extract: Calling LLM for fact extraction "
            "(%d chars input)",
            len(prompt),
        )

        try:
            result = self._provider.chat(
                messages=messages,
                max_tokens=_FACT_EXTRACTION_MAX_TOKENS,
            )
            raw_content = result["content"]
            parsed = self._parse_extraction_response(raw_content)
            logger.info(
                "FactExtractor.extract: Extracted case_type=%s, "
                "completeness=%.2f, is_ready=%s",
                parsed.case_type,
                parsed.completeness_score,
                parsed.is_ready,
            )
            return parsed

        except Exception as e:
            logger.exception(
                "FactExtractor.extract: LLM call failed: %s", e
            )
            # Return a safe fallback
            return FactExtractionResult(
                case_type="other",
                facts=existing_profile or {},
                completeness_score=0.0,
                missing_facts=["خطا در ارتباط با سامانه هوش مصنوعی"],
                next_question=(
                    "متأسفانه در پردازش درخواست شما خطایی رخ داد. "
                    "لطفاً مجدداً تلاش کنید."
                ),
                is_ready=False,
            )

    def _parse_extraction_response(
        self, raw_content: str
    ) -> FactExtractionResult:
        """Parse the LLM JSON response for fact extraction.

        Args:
            raw_content: The raw string from the chat provider.

        Returns:
            A :class:`FactExtractionResult`.
        """
        cleaned = raw_content.strip()

        # Strip markdown code fences
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            elif "```" in cleaned:
                cleaned = cleaned[: cleaned.rfind("```")].strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try non-strict parsing
            try:
                data = json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                logger.warning(
                    "_parse_extraction_response: Invalid JSON from LLM, "
                    "raw=%.200s",
                    raw_content,
                )
                return FactExtractionResult()

        case_type = data.get("case_type", "")
        if not isinstance(case_type, str):
            case_type = ""

        facts = data.get("facts", {})
        if not isinstance(facts, dict):
            facts = {}

        completeness_score = data.get("completeness_score", 0.0)
        if not isinstance(completeness_score, (int, float)):
            completeness_score = 0.0
        completeness_score = max(0.0, min(1.0, float(completeness_score)))

        missing_facts = data.get("missing_facts", [])
        if not isinstance(missing_facts, list):
            missing_facts = []

        next_question = data.get("next_question", "")
        if not isinstance(next_question, str):
            next_question = ""

        is_ready = data.get("is_ready", False)
        if not isinstance(is_ready, bool):
            is_ready = completeness_score >= _COMPLETENESS_THRESHOLD

        return FactExtractionResult(
            case_type=case_type,
            facts=facts,
            completeness_score=completeness_score,
            missing_facts=missing_facts,
            next_question=next_question,
            is_ready=is_ready,
        )


# ---------------------------------------------------------------------------
# CompletenessChecker
# ---------------------------------------------------------------------------


class CompletenessChecker:
    """Identifies missing critical facts based on case type.

    Uses an LLM call to evaluate the completeness of the case profile
    and determine the most important missing information.
    """

    def __init__(self) -> None:
        self._provider = get_chat_provider()

    def check(
        self,
        case_type: str,
        facts: dict[str, Any],
    ) -> FactExtractionResult:
        """Check completeness of a case profile.

        Args:
            case_type: The identified case type.
            facts: The structured facts dict from the case profile.

        Returns:
            A :class:`FactExtractionResult` with completeness assessment
            and next question if not ready.
        """
        prompt = (
            f"Case Type: {case_type}\n\n"
            f"Extracted Facts:\n"
            f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": COMPLETENESS_CHECKER_PROMPT},
            {"role": "user", "content": prompt},
        ]

        logger.info(
            "CompletenessChecker.check: Checking completeness for "
            "case_type=%s",
            case_type,
        )

        try:
            result = self._provider.chat(
                messages=messages,
                max_tokens=_FACT_EXTRACTION_MAX_TOKENS,
            )
            raw_content = result["content"]
            parsed = self._parse_checker_response(raw_content)
            logger.info(
                "CompletenessChecker.check: score=%.2f, is_ready=%s",
                parsed.completeness_score,
                parsed.is_ready,
            )
            return parsed

        except Exception as e:
            logger.exception(
                "CompletenessChecker.check: LLM call failed: %s", e
            )
            return FactExtractionResult(
                case_type=case_type,
                facts=facts,
                completeness_score=0.0,
                missing_facts=["خطا در بررسی کامل بودن اطلاعات"],
                next_question=(
                    "متأسفانه در بررسی اطلاعات خطایی رخ داد. "
                    "لطفاً مجدداً تلاش کنید."
                ),
                is_ready=False,
            )

    def _parse_checker_response(
        self, raw_content: str
    ) -> FactExtractionResult:
        """Parse the LLM JSON response for completeness checking.

        Args:
            raw_content: The raw string from the chat provider.

        Returns:
            A :class:`FactExtractionResult`.
        """
        cleaned = raw_content.strip()

        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            elif "```" in cleaned:
                cleaned = cleaned[: cleaned.rfind("```")].strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                data = json.loads(cleaned, strict=False)
            except json.JSONDecodeError:
                logger.warning(
                    "_parse_checker_response: Invalid JSON, raw=%.200s",
                    raw_content,
                )
                return FactExtractionResult()

        completeness_score = data.get("completeness_score", 0.0)
        if not isinstance(completeness_score, (int, float)):
            completeness_score = 0.0
        completeness_score = max(0.0, min(1.0, float(completeness_score)))

        missing_facts = data.get("missing_facts", [])
        if not isinstance(missing_facts, list):
            missing_facts = []

        next_question = data.get("next_question", "")
        if not isinstance(next_question, str):
            next_question = ""

        is_ready = data.get("is_ready", False)
        if not isinstance(is_ready, bool):
            is_ready = completeness_score >= _COMPLETENESS_THRESHOLD

        return FactExtractionResult(
            completeness_score=completeness_score,
            missing_facts=missing_facts,
            next_question=next_question,
            is_ready=is_ready,
        )


# ---------------------------------------------------------------------------
# StrategicAnalyzer
# ---------------------------------------------------------------------------


class StrategicAnalyzer:
    """Evaluates case strength by researching laws/precedents and running
    LLM analysis to generate a :class:`StrategicReport`.

    The analyzer:
    1. Routes the case description to identify relevant legal hubs.
    2. Searches all relevant hubs via :func:`multi_hub_search`.
    3. Builds a legal context from retrieved chunks.
    4. Calls the LLM to analyse facts against the legal context.
    5. Generates a structured :class:`AnalysisResult`.
    """

    def __init__(self) -> None:
        self._provider = get_chat_provider()

    def analyze(
        self,
        case_type: str,
        facts: dict[str, Any],
    ) -> AnalysisResult:
        """Run the full strategic analysis pipeline.

        Args:
            case_type: The identified case type.
            facts: The structured facts dict from the case profile.

        Returns:
            An :class:`AnalysisResult` with the complete strategic analysis.
        """
        # Build a natural language case description from the structured facts
        case_description = self._build_case_description(case_type, facts)

        logger.info(
            "StrategicAnalyzer.analyze: Starting analysis for "
            "case_type=%s, facts=%d keys",
            case_type,
            len(facts),
        )
        logger.debug(
            "StrategicAnalyzer.analyze: Case description: %s",
            case_description,
        )

        # ------------------------------------------------------------------
        # Step 1: Route the case to relevant legal hubs
        # ------------------------------------------------------------------
        try:
            router_result = route_question(case_description)
            active_hubs = [
                hub for hub, sq in router_result.sub_queries.items()
                if sq.fts_query or sq.vector_query
            ]
            logger.info(
                "StrategicAnalyzer.analyze: Router identified active hubs: %s",
                active_hubs,
            )
            # Log per-hub query details for debugging
            for hub, sq in router_result.sub_queries.items():
                logger.debug(
                    "StrategicAnalyzer.analyze: Hub '%s' — "
                    "fts_query=%.120s, vector_query=%.120s",
                    hub, sq.fts_query or "", sq.vector_query or "",
                )
        except Exception as e:
            logger.exception(
                "StrategicAnalyzer.analyze: Question routing failed: %s", e
            )
            # Fallback: use all hubs with the case description
            router_result = RouterResult(
                sub_queries={
                    "legislation": SubQuery(
                        fts_query=case_description,
                        vector_query=case_description,
                    ),
                    "judicial_precedent": SubQuery(
                        fts_query=case_description,
                        vector_query=case_description,
                    ),
                    "advisory_opinion": SubQuery(
                        fts_query=case_description,
                        vector_query=case_description,
                    ),
                },
                hypothetical_answer=case_description,
                reasoning="Fallback: all hubs due to routing failure.",
            )

        # ------------------------------------------------------------------
        # Step 2: Search all relevant hubs (parallel)
        # ------------------------------------------------------------------
        try:
            hub_results = multi_hub_search(
                router_result=router_result,
                top_k_per_hub=_STRATEGY_TOP_K_PER_HUB,
            )
        except Exception as e:
            logger.exception(
                "StrategicAnalyzer.analyze: Multi-hub search failed: %s", e
            )
            hub_results = {}

        # Filter chunks by relevance to case type
        for hub_type, hub_data in hub_results.items():
            chunks = hub_data.get("chunks", [])
            if chunks:
                hub_data["chunks"] = self._filter_relevant_chunks(
                    chunks, case_type,
                )

        # Build legal context from filtered chunks
        legal_context = build_global_context(hub_results)

        # Collect all chunks for citation extraction
        all_chunks: list[dict[str, Any]] = []
        for hub_data in hub_results.values():
            all_chunks.extend(hub_data.get("chunks", []))

        logger.info(
            "StrategicAnalyzer.analyze: Retrieved %d chunks total from %d hubs",
            len(all_chunks),
            len(hub_results),
        )

        # ------------------------------------------------------------------
        # Step 3: LLM analysis
        # ------------------------------------------------------------------
        analysis_prompt = self._build_analysis_prompt(
            case_type=case_type,
            facts=facts,
            case_description=case_description,
            legal_context=legal_context,
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": STRATEGIC_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": analysis_prompt},
        ]

        logger.info(
            "StrategicAnalyzer.analyze: Calling LLM for strategic analysis "
            "(%d chars input)",
            len(analysis_prompt),
        )

        try:
            result = self._provider.chat(
                messages=messages,
                max_tokens=_ANALYSIS_MAX_TOKENS,
            )
            raw_content = result["content"]
            analysis = self._parse_analysis_response(raw_content)

            # Extract citations from the raw report
            from conversations.rag_service import extract_citations

            sources = extract_citations(analysis.raw_report, all_chunks)

            logger.info(
                "StrategicAnalyzer.analyze: Analysis complete — "
                "success_prob=%.2f, %d strengths, %d weaknesses",
                analysis.success_probability,
                len(analysis.strengths),
                len(analysis.weaknesses),
            )

            return analysis

        except Exception as e:
            logger.exception(
                "StrategicAnalyzer.analyze: LLM analysis failed: %s", e
            )
            return AnalysisResult(
                success_probability=0.0,
                summary=(
                    "تحلیل استراتژیک به دلیل خطا در پردازش قابل انجام نبود. "
                    "لطفاً مجدداً تلاش کنید."
                ),
                strengths=[],
                weaknesses=[],
                risks=[f"خطای سیستمی: {str(e)}"],
                recommendations=[
                    "مجدداً تلاش کنید",
                    "در صورت تکرار خطا با پشتیبانی تماس بگیرید",
                ],
                raw_report=(
                    "# گزارش تحلیل استراتژیک\n\n"
                    "## خطا\n"
                    f"تحلیل به دلیل خطا در پردازش قابل انجام نبود: {str(e)}\n"
                ),
            )

    def _filter_relevant_chunks(
        self,
        all_chunks: list[dict[str, Any]],
        case_type: str,
    ) -> list[dict[str, Any]]:
        """Filter chunks by relevance to the case type.

        Removes chunks that are clearly irrelevant to avoid confusing the LLM.
        Keeps chunks that contain case-type-specific keywords OR have a
        relevance_score >= 0.5.

        Args:
            all_chunks: List of chunk dicts, each with 'content' and
                        'relevance_score' keys.
            case_type: The case type identifier (e.g. 'contract_dispute').

        Returns:
            Filtered list of relevant chunks.
        """
        case_keywords: dict[str, list[str]] = {
            "contract_dispute": [
                "قرارداد", "اجاره", "موجر", "مستاجر", "تخلیه", "اجاره بها",
                "فسخ", "انقضا", "مدت", "عقد", "التزام", "تعهد", "ماده",
            ],
            "family_law": [
                "طلاق", "مهریه", "نفقه", "حضانت", "ازدواج", "نکاح",
                "رجوع", "تمکین", "شوهر", "زوجه", "زوج",
            ],
            "criminal": [
                "مجازات", "جرم", "کیفر", "حبس", "جزای نقدی", "شکایت",
                "بزه", "دادرسی", "تحقیقات", "قاضی", "دادگاه",
            ],
            "civil": [
                "مسئولیت مدنی", "خسارت", "ضمان", "عقد", "قرارداد",
                "تعهد", "الزام", "تحویل", "مبیع", "ثمن",
            ],
            "labour": [
                "کارگر", "کارفرما", "حقوق", "مزایا", "بیمه", "بازنشستگی",
                "اخطار", "فسخ قرارداد کار", "پایان کار",
            ],
            "inheritance": [
                "ارث", "وصیت", "وارث", "ترکه", "سهم", "حصه",
                "طبقه", "فرزند", "همسر", "والدین",
            ],
            "property": [
                "ملک", "زمین", "آپارتمان", "سند", "ثبت", "حدود",
                "تصرف", "منافع", "عین", "ملکی",
            ],
        }

        keywords = case_keywords.get(case_type, [])
        if not keywords:
            return all_chunks

        filtered: list[dict[str, Any]] = []
        for chunk in all_chunks:
            content = chunk.get("content", "")
            score = chunk.get("relevance_score", 0.0)

            # Check if chunk contains any relevant keywords
            has_keyword = any(kw in content for kw in keywords)

            # Keep chunks with high relevance scores even without keywords
            # (they may contain semantically relevant content)
            if has_keyword or score >= 0.5:
                filtered.append(chunk)
            else:
                logger.debug(
                    "_filter_relevant_chunks: Filtered out chunk "
                    "(score=%.4f, no relevant keywords): %.100s",
                    score, content,
                )

        logger.info(
            "_filter_relevant_chunks: Filtered %d/%d chunks for case_type=%s",
            len(all_chunks) - len(filtered),
            len(all_chunks),
            case_type,
        )

        return filtered

    def _build_case_description(
        self,
        case_type: str,
        facts: dict[str, Any],
    ) -> str:
        """Build a fluent Persian legal case description for semantic search.

        Produces a natural language description optimized for embedding similarity
        with legal documents in the knowledge base, rather than a JSON dump.

        Args:
            case_type: The case type identifier (e.g. 'contract_dispute').
            facts: The structured facts dict.

        Returns:
            A Persian natural language description of the case, with fields
            separated by `` | ``.
        """
        # Map case_type to Persian labels
        case_type_labels = {
            "contract_dispute": "اختلافات قراردادی",
            "family_law": "دعاوی خانواده",
            "criminal": "دعاوی کیفری",
            "civil": "دعاوی حقوقی",
            "labour": "دعاوی کار و کارگری",
            "inheritance": "دعاوی ارث",
            "property": "دعاوی ملکی",
            "other": "سایر",
        }

        parts = [f"پرونده {case_type_labels.get(case_type, case_type)}"]

        # Add parties
        parties = facts.get("parties", {})
        if parties:
            if isinstance(parties, dict):
                party_str = " و ".join(
                    f"{k}: {v}" for k, v in parties.items()
                )
                parts.append(f"طرفین دعوا: {party_str}")
            elif isinstance(parties, str):
                parts.append(f"طرفین دعوا: {parties}")

        # Add claims
        claims = facts.get("claims", "")
        if claims:
            parts.append(f"خواسته: {claims}")

        # Add amount (format with commas for readability)
        amount = facts.get("amount")
        if amount:
            try:
                amount_val = float(amount)
                if amount_val == int(amount_val):
                    amount_str = f"{int(amount_val):,}"
                else:
                    amount_str = str(amount)
                parts.append(f"مبلغ: {amount_str} تومان")
            except (ValueError, TypeError):
                parts.append(f"مبلغ: {amount}")

        # Add timeline
        timeline = facts.get("timeline", "")
        if timeline:
            parts.append(f"زمان‌بندی: {timeline}")

        # Add jurisdiction
        jurisdiction = facts.get("jurisdiction", "")
        if jurisdiction:
            parts.append(f"مرجع قضایی: {jurisdiction}")

        # Add evidence
        evidence = facts.get("evidence", "")
        if evidence:
            parts.append(f"ادله و مدارک: {evidence}")

        # Add current status
        current_status = facts.get("current_status", "")
        if current_status:
            parts.append(f"وضعیت فعلی: {current_status}")

        # Add any remaining keys as key-value strings
        known_keys = {
            "parties", "claims", "amount", "timeline",
            "jurisdiction", "evidence", "current_status",
        }
        for key, value in facts.items():
            if key not in known_keys:
                if isinstance(value, str) and value:
                    parts.append(f"{key}: {value}")

        return " | ".join(parts)

    def _build_analysis_prompt(
        self,
        case_type: str,
        facts: dict[str, Any],
        case_description: str,
        legal_context: str,
    ) -> str:
        """Build the analysis prompt for the LLM.

        Args:
            case_type: The case type identifier.
            facts: The structured facts dict.
            case_description: Natural language case description.
            legal_context: Formatted legal context from hub search results.

        Returns:
            The analysis prompt string.
        """
        prompt_parts: list[str] = [
            "## Case Information\n",
            f"**Case Type:** {case_type}\n",
            "**Case Description (Persian):**\n"
            f"{case_description}\n",
            "**Extracted Facts (JSON):**\n"
            + json.dumps(facts, ensure_ascii=False, indent=2),
        ]

        if legal_context:
            prompt_parts.extend([
                "\n## Retrieved Legal Context\n",
                "The following legal information was retrieved from Persian "
                "legal knowledge hubs. Use this to ground your analysis.\n"
                "\n"
                "**IMPORTANT — Context Relevance Check:**\n"
                "If the retrieved legal context is not relevant to the case, "
                "ignore it and base your analysis on general legal principles. "
                "Do NOT cite laws or precedents that are not relevant to the "
                "case facts.\n",
                legal_context,
            ])
        else:
            prompt_parts.extend([
                "\n## Legal Context\n",
                "No specific legal context was retrieved from the knowledge "
                "base. Base your analysis on general legal principles and "
                "the facts provided.",
            ])

        prompt_parts.append(
            "\n## Task\n"
            "Based on the case information and legal context above, produce "
            "a comprehensive strategic analysis in Persian. Include success "
            "probability, strengths, weaknesses, risks, recommendations, "
            "and a full markdown report."
        )

        return "\n".join(prompt_parts)

    # ------------------------------------------------------------------
    # JSON Parsing — delegates to module-level functions
    # ------------------------------------------------------------------

    def _parse_analysis_response(
        self, raw_content: str
    ) -> AnalysisResult:
        """Parse the LLM JSON response for strategic analysis.

        Delegates to the module-level :func:`parse_analysis_response`.
        """
        return parse_analysis_response(raw_content)


# ---------------------------------------------------------------------------
# Module-level JSON Parsing Functions
# ---------------------------------------------------------------------------
# These are module-level so they can be used by both StrategicAnalyzer
# (via delegation) and StrategistService (via wrapper methods).


def _extract_json_from_fence(raw_content: str) -> str | None:
    """Extract JSON from markdown code fences using regex.

    Handles:
    - ```json\\n{...}\\n```
    - ```\\n{...}\\n```
    - ```json\\n{...}\\n``` (with trailing whitespace)
    - {json} without any fences
    - Truncated responses where the closing ``` is missing
    """
    # Pattern 1: Content inside ```json or ``` fences
    # Uses (?:```|$) to handle truncated responses missing the closing fence
    fence_pattern = r'```(?:json)?\s*\n(.*?)(?:```|$)'
    match = re.search(fence_pattern, raw_content, re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        if extracted:
            return extracted

    # Pattern 2: If raw content starts with ```json or ``` but regex failed,
    # manually strip the fence prefix and try to parse the rest
    stripped = raw_content.strip()
    for prefix in ('```json\n', '```\n', '```json', '```'):
        if stripped.startswith(prefix):
            after_fence = stripped[len(prefix):].strip()
            if after_fence:
                return after_fence

    # Pattern 3: Try to find a top-level JSON object/array directly
    if stripped.startswith('{') or stripped.startswith('['):
        return stripped

    return None


def _repair_json(text: str) -> str:
    """Attempt to repair common JSON issues from LLM output.

    Fixes:
    - Trailing commas before ``]`` or ``}``
    - Best-effort single-quote to double-quote replacement for keys
    """
    # 1. Remove trailing commas before ] or }
    text = re.sub(r',\s*([\]}])', r'\1', text)

    # 2. Best-effort: replace single quotes with double quotes
    #    Only targets patterns like '{key}': or '{string_value}'
    #    This is a heuristic and may not cover all edge cases.
    text = re.sub(r"(?<!\\)'", '"', text)

    return text


def _extract_fields_via_regex(text: str) -> dict | None:
    """Extract structured fields using regex as last-resort fallback.

    Attempts to pull all structured fields from arbitrary text when JSON
    parsing has failed entirely. Uses ``re.DOTALL`` for multi-line values
    and handles Persian text with newlines and quotes.
    """
    result: dict[str, Any] = {}

    # --- Scalar fields ---
    prob = re.search(r'"success_probability"\s*:\s*([0-9.]+)', text)
    if prob:
        result["success_probability"] = float(prob.group(1))

    # Multi-line summary: match until the next field or closing brace
    summary = re.search(
        r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text,
        re.DOTALL,
    )
    if summary:
        result["summary"] = summary.group(1).strip()

    # --- Array fields ---
    for field in ("strengths", "weaknesses", "risks", "recommendations"):
        arr = re.search(
            rf'"{field}"\s*:\s*\[(.*?)\]',
            text,
            re.DOTALL,
        )
        if arr:
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', arr.group(1))
            if items:
                result[field] = [item.strip() for item in items]

    # --- raw_report (multi-line markdown string) ---
    raw_report = re.search(
        r'"raw_report"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text,
        re.DOTALL,
    )
    if raw_report:
        result["raw_report"] = raw_report.group(1).strip()

    return result if result else None


def _build_error_result(raw_content: str) -> AnalysisResult:
    """Build an ``AnalysisResult`` with an error report when parsing fails.

    Returns a result with ``success_probability=0.0`` and a Persian
    ``raw_report`` explaining the parsing failure.
    """
    logger.error(
        "_parse_analysis_response: All parsing strategies failed. "
        "Full raw_content=%s",
        raw_content,
    )

    error_report = (
        "# گزارش تحلیل استراتژیک\n\n"
        "## خطا در پردازش\n\n"
        "متأسفانه در پردازش پاسخ تحلیل استراتژیک خطایی رخ داد. "
        "لطفاً دوباره تلاش کنید.\n\n"
        "### جزئیات فنی\n\n"
        "سیستم قادر به تجزیه پاسخ دریافتی از مدل زبانی نبود. "
        "این مشکل معمولاً موقتی است و با تلاش مجدد برطرف می‌شود.\n"
    )

    return AnalysisResult(
        success_probability=0.0,
        summary="خطا در پردازش تحلیل استراتژیک",
        raw_report=error_report,
    )


def parse_analysis_response(raw_content: str) -> AnalysisResult:
    """Parse the LLM JSON response for strategic analysis.

    Uses a multi-strategy pipeline with graceful degradation:

    1. Extract JSON from markdown code fences (``_extract_json_from_fence``)
    2. Try ``json.loads`` → ``json.loads(strict=False)``
    3. Repair common LLM JSON issues (``_repair_json``) and retry
    4. If fence extraction returned None, try to find any ``{...}`` block
       in the raw content using a lenient regex
    5. Regex-based field extraction (``_extract_fields_via_regex``) on
       the raw content as last resort
    6. Build error result (``_build_error_result``) if all strategies fail

    Args:
        raw_content: The raw string from the chat provider.

    Returns:
        An :class:`AnalysisResult`.
    """
    # ------------------------------------------------------------------
    # Stage 1: Extract JSON from markdown code fences
    # ------------------------------------------------------------------
    json_str = _extract_json_from_fence(raw_content)
    data: dict[str, Any] | None = None
    strategy: str = ""

    if json_str is not None:
        # ------------------------------------------------------------------
        # Stage 2: Try json.loads (strict) → json.loads (non-strict)
        # ------------------------------------------------------------------
        for parser, label in [
            (json.loads, "json.loads"),
            (lambda s: json.loads(s, strict=False), "json.loads(strict=False)"),
        ]:
            try:
                data = parser(json_str)
                strategy = label
                break
            except json.JSONDecodeError:
                continue

        # ------------------------------------------------------------------
        # Stage 3: Repair and retry
        # ------------------------------------------------------------------
        if data is None:
            logger.warning(
                "_parse_analysis_response [stage=repair]: "
                "json.loads failed, attempting repair"
            )
            try:
                repaired = _repair_json(json_str)
                data = json.loads(repaired)
                strategy = "repair_json"
            except json.JSONDecodeError:
                pass

        # ------------------------------------------------------------------
        # Stage 4: Regex-based field extraction on extracted JSON string
        # ------------------------------------------------------------------
        if data is None:
            logger.warning(
                "_parse_analysis_response [stage=regex]: "
                "JSON parsing failed, attempting regex on extracted content"
            )
            data = _extract_fields_via_regex(json_str)
            if data is not None:
                strategy = "regex_fallback"
    else:
        logger.warning(
            "_parse_analysis_response [stage=extract]: "
            "No JSON found in response via fence extraction"
        )

    # ------------------------------------------------------------------
    # Stage 5: If fence extraction failed, try lenient {…} block search
    # directly on the raw content
    # ------------------------------------------------------------------
    if data is None:
        logger.warning(
            "_parse_analysis_response [stage=brace_search]: "
            "Attempting lenient {…} block extraction on raw content"
        )
        brace_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(0)
            # Try to parse the brace block as JSON
            for parser, label in [
                (json.loads, "brace_json.loads"),
                (lambda s: json.loads(s, strict=False), "brace_json.loads(strict=False)"),
            ]:
                try:
                    data = parser(candidate)
                    strategy = label
                    break
                except json.JSONDecodeError:
                    continue
            # If still no data, try repair on the brace block
            if data is None:
                try:
                    repaired = _repair_json(candidate)
                    data = json.loads(repaired)
                    strategy = "brace_repair_json"
                except json.JSONDecodeError:
                    pass
            # If still no data, try regex extraction on the brace block
            if data is None:
                data = _extract_fields_via_regex(candidate)
                if data is not None:
                    strategy = "brace_regex_fallback"

    # ------------------------------------------------------------------
    # Stage 6: Regex-based field extraction directly on raw content
    # (absolute last resort before error result)
    # ------------------------------------------------------------------
    if data is None:
        logger.warning(
            "_parse_analysis_response [stage=raw_regex]: "
            "Attempting regex extraction directly on raw content"
        )
        data = _extract_fields_via_regex(raw_content)
        if data is not None:
            strategy = "raw_regex_fallback"

    # ------------------------------------------------------------------
    # Stage 7: If all strategies failed, return error result
    # ------------------------------------------------------------------
    if data is None:
        logger.warning(
            "_parse_analysis_response [stage=final]: "
            "All parsing strategies failed"
        )
        return _build_error_result(raw_content)

    # Log which strategy succeeded
    logger.info(
        "_parse_analysis_response: Parsing succeeded via %s",
        strategy,
    )

    # ------------------------------------------------------------------
    # Extract structured fields from parsed data
    # ------------------------------------------------------------------
    success_probability = data.get("success_probability", 0.0)
    if not isinstance(success_probability, (int, float)):
        success_probability = 0.0
    success_probability = max(0.0, min(1.0, float(success_probability)))

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    strengths = data.get("strengths", [])
    if not isinstance(strengths, list):
        strengths = []

    weaknesses = data.get("weaknesses", [])
    if not isinstance(weaknesses, list):
        weaknesses = []

    risks = data.get("risks", [])
    if not isinstance(risks, list):
        risks = []

    recommendations = data.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []

    applicable_laws = data.get("applicable_laws", [])
    if not isinstance(applicable_laws, list):
        applicable_laws = []

    applicable_precedents = data.get("applicable_precedents", [])
    if not isinstance(applicable_precedents, list):
        applicable_precedents = []

    raw_report = data.get("raw_report", "")
    if not isinstance(raw_report, str):
        raw_report = ""

    # If no raw_report was provided, build one from the structured fields
    if not raw_report:
        logger.info(
            "parse_analysis_response: raw_report missing — "
            "building fallback report from structured fields "
            "(strategy=%s)",
            strategy,
        )
        raw_report = _build_fallback_report(
            success_probability=success_probability,
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            risks=risks,
            recommendations=recommendations,
            applicable_laws=applicable_laws,
            applicable_precedents=applicable_precedents,
        )
    else:
        logger.info(
            "parse_analysis_response: raw_report successfully extracted "
            "(%d chars, strategy=%s)",
            len(raw_report),
            strategy,
        )

    return AnalysisResult(
        success_probability=success_probability,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        risks=risks,
        recommendations=recommendations,
        applicable_laws=applicable_laws,
        applicable_precedents=applicable_precedents,
        raw_report=raw_report,
    )


def _build_fallback_report(
    success_probability: float,
    summary: str,
    strengths: list[str],
    weaknesses: list[str],
    risks: list[str],
    recommendations: list[str],
    applicable_laws: list[dict[str, Any]],
    applicable_precedents: list[dict[str, Any]],
) -> str:
    """Build a Persian markdown report from structured fields.

    Used when the LLM didn't return a ``raw_report`` field.

    Args:
        success_probability: 0.0–1.0 success probability.
        summary: Persian summary text.
        strengths: List of strengths.
        weaknesses: List of weaknesses.
        risks: List of risks.
        recommendations: List of recommendations.
        applicable_laws: List of applicable law dicts.
        applicable_precedents: List of applicable precedent dicts.

    Returns:
        A Persian markdown report string.
    """
    lines = [
        "# گزارش تحلیل استراتژیک\n",
        "## خلاصه",
        summary,
        "",
        f"**احتمال موفقیت:** {success_probability * 100:.0f}%\n",
    ]

    if strengths:
        lines.append("## نقاط قوت")
        for s in strengths:
            lines.append(f"- {s}")
        lines.append("")

    if weaknesses:
        lines.append("## نقاط ضعف")
        for w in weaknesses:
            lines.append(f"- {w}")
        lines.append("")

    if risks:
        lines.append("## ریسک‌ها")
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")

    if recommendations:
        lines.append("## توصیه‌ها")
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    if applicable_laws:
        lines.append("## قوانین مرتبط")
        for law in applicable_laws:
            title = law.get("title", "")
            articles = law.get("articles", "")
            citations = law.get("citations", "")
            line_parts = [f"- **{title}**"]
            if articles:
                line_parts.append(f" — {articles}")
            if citations:
                line_parts.append(f" ({citations})")
            lines.append("".join(line_parts))
        lines.append("")

    if applicable_precedents:
        lines.append("## رویه‌های قضایی مرتبط")
        for prec in applicable_precedents:
            title = prec.get("title", "")
            number = prec.get("number", "")
            summary = prec.get("summary", "")
            line_parts = [f"- **{title}**"]
            if number:
                line_parts.append(f" (شماره {number})")
            if summary:
                line_parts.append(f": {summary}")
            lines.append("".join(line_parts))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# StrategistService — Main Orchestrator
# ---------------------------------------------------------------------------


class StrategistService:
    """Main orchestrator for the Interactive Strategist pipeline.

    Manages the guided interview → research → analysis flow:

    1. **Fact Extraction**: LLM extracts structured facts from user messages
       into a :class:`CaseProfile` model.
    2. **Completeness Checking**: LLM evaluates whether enough facts have
       been gathered; if not, generates a targeted follow-up question.
    3. **Strategic Analysis**: When enough facts are gathered, runs
       :class:`StrategicAnalyzer` to research laws/precedents and generate
       a :class:`StrategicReport`.
    4. **Streaming Output**: Yields ``(event_type, data)`` tuples for the
       streaming SSE response.

    The service persists state to the database:
    - :class:`CaseProfile` is created/updated after each fact extraction.
    - :class:`StrategicReport` is created after analysis completes.
    """

    # ------------------------------------------------------------------
    # JSON Parsing Wrappers
    # ------------------------------------------------------------------
    # These delegate to module-level functions so they can be tested
    # via the StrategistService interface.

    def _extract_json_from_fence(self, raw_content: str) -> str | None:
        """Extract JSON from markdown code fences.

        Delegates to :func:`_extract_json_from_fence`.
        """
        return _extract_json_from_fence(raw_content)

    def _repair_json(self, text: str) -> str:
        """Repair common JSON issues.

        Delegates to :func:`_repair_json`.
        """
        return _repair_json(text)

    def _extract_fields_via_regex(self, text: str) -> dict | None:
        """Extract fields via regex fallback.

        Delegates to :func:`_extract_fields_via_regex`.
        """
        return _extract_fields_via_regex(text)

    def _build_error_result(self, raw_content: str) -> AnalysisResult:
        """Build an error result when parsing fails.

        Delegates to :func:`_build_error_result`.
        """
        return _build_error_result(raw_content)

    def _parse_analysis_response(
        self, raw_content: str
    ) -> AnalysisResult:
        """Parse the LLM JSON response for strategic analysis.

        Delegates to :func:`parse_analysis_response`.
        """
        return parse_analysis_response(raw_content)

    def __init__(self) -> None:
        self._fact_extractor = FactExtractor()
        self._completeness_checker = CompletenessChecker()
        self._strategic_analyzer = StrategicAnalyzer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_message(
        self,
        message: str,
        conversation_history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
    ) -> Generator[tuple[str, dict[str, Any]], None, None]:
        """Process a user message through the strategist pipeline.

        This is the main entry point called by the views. It yields
        ``(event_type, data)`` tuples for streaming:

        - ``("progress", {"status": str})`` — Pipeline stage updates.
        - ``("token", {"content": str})`` — Content tokens (questions or
          report text).
        - ``("done", {...})`` — Final event with full result.

        Args:
            message: The user's latest message text.
            conversation_history: Optional list of prior message dicts.
            conversation_id: Optional conversation UUID for persisting
                :class:`CaseProfile` and :class:`StrategicReport`.

        Yields:
            ``(event_type, data)`` tuples for the streaming response.
        """
        logger.info(
            "StrategistService.process_message: Processing message "
            "(%d chars, conv=%s)",
            len(message),
            conversation_id,
        )

        # ------------------------------------------------------------------
        # Step 1: Extract facts from the user message
        # ------------------------------------------------------------------
        yield ("progress", {"status": "Analyzing your case facts..."})

        # Load existing profile if this conversation already has one
        existing_profile: dict[str, Any] | None = None
        existing_case_profile = None
        if conversation_id:
            try:
                existing_case_profile = CaseProfile.objects.get(
                    conversation_id=conversation_id
                )
                existing_profile = existing_case_profile.facts
                logger.info(
                    "StrategistService: Loaded existing CaseProfile for conv=%s "
                    "(case_type=%s, score=%.2f)",
                    conversation_id,
                    existing_case_profile.case_type,
                    existing_case_profile.completeness_score,
                )
            except CaseProfile.DoesNotExist:
                logger.info(
                    "StrategistService: No existing CaseProfile for conv=%s",
                    conversation_id,
                )

        extraction_result = self._fact_extractor.extract(
            user_message=message,
            conversation_history=conversation_history,
            existing_profile=existing_profile,
        )

        # Persist/update the CaseProfile
        if conversation_id:
            self._save_case_profile(
                conversation_id=conversation_id,
                case_type=extraction_result.case_type,
                facts=extraction_result.facts,
                completeness_score=extraction_result.completeness_score,
                is_complete=extraction_result.is_ready,
            )

        logger.info(
            "StrategistService: Fact extraction complete — "
            "case_type=%s, score=%.2f, is_ready=%s",
            extraction_result.case_type,
            extraction_result.completeness_score,
            extraction_result.is_ready,
        )

        # ------------------------------------------------------------------
        # Step 2: Check readiness — if not ready, ask a follow-up question
        # ------------------------------------------------------------------
        if not extraction_result.is_ready:
            # Use the next_question from the extraction (or run completeness
            # checker for a more targeted question)
            next_question = extraction_result.next_question

            # If the extractor didn't generate a question, run the
            # completeness checker for a more targeted one
            if not next_question and extraction_result.facts:
                logger.info(
                    "StrategistService: Running CompletenessChecker for "
                    "targeted question (case_type=%s)",
                    extraction_result.case_type,
                )
                yield ("progress", {"status": "Identifying missing information..."})
                checker_result = self._completeness_checker.check(
                    case_type=extraction_result.case_type,
                    facts=extraction_result.facts,
                )
                next_question = checker_result.next_question

            if next_question:
                logger.info(
                    "StrategistService: Yielding interview question to user"
                )
                yield ("token", {"content": next_question})
                yield ("done", {
                    "content": next_question,
                    "sources": [],
                    "token_usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "is_interview": True,
                    "case_type": extraction_result.case_type,
                    "completeness_score": extraction_result.completeness_score,
                })
                return

        # ------------------------------------------------------------------
        # Step 3: Run strategic analysis (case is ready)
        # ------------------------------------------------------------------
        logger.info(
            "StrategistService: Case is ready — running strategic analysis "
            "(case_type=%s)",
            extraction_result.case_type,
        )
        yield ("progress", {"status": "Researching applicable laws and precedents..."})

        analysis_result = self._strategic_analyzer.analyze(
            case_type=extraction_result.case_type,
            facts=extraction_result.facts,
        )

        # ------------------------------------------------------------------
        # Step 4: Persist the StrategicReport
        # ------------------------------------------------------------------
        if conversation_id and extraction_result.case_type:
            self._save_strategic_report(
                conversation_id=conversation_id,
                case_profile_data={
                    "case_type": extraction_result.case_type,
                    "facts": extraction_result.facts,
                    "completeness_score": extraction_result.completeness_score,
                    "is_complete": True,
                },
                analysis_result=analysis_result,
            )

        # ------------------------------------------------------------------
        # Step 5: Stream the report tokens
        # ------------------------------------------------------------------
        logger.info(
            "StrategistService: Streaming strategic report "
            "(%d chars)",
            len(analysis_result.raw_report),
        )

        # Stream the raw report token by token
        report_text = analysis_result.raw_report
        if report_text:
            # Yield in chunks for smoother streaming
            chunk_size = 50
            for i in range(0, len(report_text), chunk_size):
                chunk = report_text[i:i + chunk_size]
                yield ("token", {"content": chunk})

        yield ("done", {
            "content": analysis_result.raw_report,
            "sources": [],
            "token_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "is_interview": False,
            "case_type": extraction_result.case_type,
            "completeness_score": 1.0,
            "analysis": {
                "success_probability": analysis_result.success_probability,
                "summary": analysis_result.summary,
                "strengths": analysis_result.strengths,
                "weaknesses": analysis_result.weaknesses,
                "risks": analysis_result.risks,
                "recommendations": analysis_result.recommendations,
                "applicable_laws": analysis_result.applicable_laws,
                "applicable_precedents": analysis_result.applicable_precedents,
            },
        })

    # ------------------------------------------------------------------
    # Persistence Helpers
    # ------------------------------------------------------------------

    def _save_case_profile(
        self,
        conversation_id: str,
        case_type: str,
        facts: dict[str, Any],
        completeness_score: float,
        is_complete: bool,
    ) -> None:
        """Create or update a :class:`CaseProfile` for the conversation.

        Args:
            conversation_id: The conversation UUID.
            case_type: The identified case type.
            facts: The structured facts dict.
            completeness_score: 0.0–1.0 completeness score.
            is_complete: Whether the profile is ready for analysis.
        """
        try:
            profile, created = CaseProfile.objects.update_or_create(
                conversation_id=conversation_id,
                defaults={
                    "case_type": case_type,
                    "facts": facts,
                    "completeness_score": completeness_score,
                    "is_complete": is_complete,
                },
            )
            logger.info(
                "StrategistService: CaseProfile %s for conv=%s "
                "(created=%s)",
                "created" if created else "updated",
                conversation_id,
                created,
            )
        except Exception as e:
            logger.exception(
                "StrategistService: Failed to save CaseProfile for conv=%s: %s",
                conversation_id,
                e,
            )

    def _save_strategic_report(
        self,
        conversation_id: str,
        case_profile_data: dict[str, Any],
        analysis_result: AnalysisResult,
    ) -> None:
        """Create a :class:`StrategicReport` for the conversation.

        Args:
            conversation_id: The conversation UUID.
            case_profile_data: Dict with case_type, facts, completeness_score,
                is_complete keys for creating/updating the CaseProfile.
            analysis_result: The :class:`AnalysisResult` from the analyzer.
        """
        try:
            # Ensure the CaseProfile exists
            profile, _ = CaseProfile.objects.update_or_create(
                conversation_id=conversation_id,
                defaults=case_profile_data,
            )

            # Create or update the StrategicReport (handles retry idempotency)
            report, created = StrategicReport.objects.update_or_create(
                conversation_id=conversation_id,
                defaults={
                    "case_profile": profile,
                    "success_probability": analysis_result.success_probability,
                    "summary": analysis_result.summary,
                    "strengths": analysis_result.strengths,
                    "weaknesses": analysis_result.weaknesses,
                    "risks": analysis_result.risks,
                    "recommendations": analysis_result.recommendations,
                    "applicable_laws": analysis_result.applicable_laws,
                    "applicable_precedents": analysis_result.applicable_precedents,
                    "raw_report": analysis_result.raw_report,
                },
            )
            logger.info(
                "StrategistService: StrategicReport %s created for conv=%s",
                report.id,
                conversation_id,
            )
        except Exception as e:
            logger.exception(
                "StrategistService: Failed to save StrategicReport for conv=%s: %s",
                conversation_id,
                e,
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

strategist_service = StrategistService()
