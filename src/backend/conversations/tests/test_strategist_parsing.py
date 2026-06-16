"""
Unit tests for the JSON parsing strategies in ``StrategistService``.

Tests cover the multi-strategy pipeline used by
:meth:`~conversations.strategist_service.StrategistService._parse_analysis_response`
and its helper methods:

- :meth:`~conversations.strategist_service.StrategistService._extract_json_from_fence`
- :meth:`~conversations.strategist_service.StrategistService._repair_json`
- :meth:`~conversations.strategist_service.StrategistService._extract_fields_via_regex`
- :meth:`~conversations.strategist_service.StrategistService._build_error_result`

All tests instantiate ``StrategistService`` directly (no DB or network needed)
except the idempotency tests which require a database.
"""

from __future__ import annotations

import uuid

import pytest

from conversations.strategist_service import AnalysisResult, StrategistService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> StrategistService:
    """Return a bare ``StrategistService`` instance for testing."""
    return StrategistService()


# ---------------------------------------------------------------------------
# _extract_json_from_fence
# ---------------------------------------------------------------------------


class TestExtractJsonFromFence:
    """Tests for :meth:`StrategistService._extract_json_from_fence`."""

    def test_extract_from_json_fence(self, service: StrategistService) -> None:
        """Extract JSON from a ```json ... ``` block."""
        raw = '```json\n{"key": "value"}\n```'
        result = service._extract_json_from_fence(raw)
        assert result == '{"key": "value"}'

    def test_extract_from_plain_fence(self, service: StrategistService) -> None:
        """Extract JSON from a ``` ... ``` block (no language tag)."""
        raw = '```\n{"key": "value"}\n```'
        result = service._extract_json_from_fence(raw)
        assert result == '{"key": "value"}'

    def test_extract_with_trailing_whitespace(self, service: StrategistService) -> None:
        """Handle trailing whitespace after closing fence."""
        raw = '```json\n{"key": "value"}\n```  \n'
        result = service._extract_json_from_fence(raw)
        assert result == '{"key": "value"}'

    def test_extract_direct_json_object(self, service: StrategistService) -> None:
        """Detect JSON that starts directly with { (no fences)."""
        raw = '{"success_probability": 0.85}'
        result = service._extract_json_from_fence(raw)
        assert result == '{"success_probability": 0.85}'

    def test_extract_direct_json_array(self, service: StrategistService) -> None:
        """Detect JSON that starts directly with [ (no fences)."""
        raw = '["a", "b"]'
        result = service._extract_json_from_fence(raw)
        assert result == '["a", "b"]'

    def test_extract_with_text_before_fence(self, service: StrategistService) -> None:
        """Extract JSON when there is text before the code fence."""
        raw = 'Here is the result:\n```json\n{"key": "value"}\n```'
        result = service._extract_json_from_fence(raw)
        assert result == '{"key": "value"}'

    def test_extract_with_text_after_fence(self, service: StrategistService) -> None:
        """Extract JSON when there is text after the code fence."""
        raw = '```json\n{"key": "value"}\n```\nSome trailing notes.'
        result = service._extract_json_from_fence(raw)
        assert result == '{"key": "value"}'

    def test_extract_no_json(self, service: StrategistService) -> None:
        """Return None when no JSON-like content is present."""
        raw = "This is just plain text without any JSON."
        result = service._extract_json_from_fence(raw)
        assert result is None

    def test_extract_empty_string(self, service: StrategistService) -> None:
        """Return None for an empty string."""
        result = service._extract_json_from_fence("")
        assert result is None


# ---------------------------------------------------------------------------
# _repair_json
# ---------------------------------------------------------------------------


class TestRepairJson:
    """Tests for :meth:`StrategistService._repair_json`."""

    def test_remove_trailing_comma_in_object(self, service: StrategistService) -> None:
        """Remove trailing comma before }."""
        raw = '{"a": 1, "b": 2,}'
        result = service._repair_json(raw)
        assert result == '{"a": 1, "b": 2}'

    def test_remove_trailing_comma_in_array(self, service: StrategistService) -> None:
        """Remove trailing comma before ]."""
        raw = '{"strengths": ["a", "b",]}'
        result = service._repair_json(raw)
        assert result == '{"strengths": ["a", "b"]}'

    def test_remove_trailing_comma_nested(self, service: StrategistService) -> None:
        """Remove trailing commas at multiple nesting levels."""
        raw = '{"a": {"b": 1,}, "c": [2, 3,],}'
        result = service._repair_json(raw)
        assert result == '{"a": {"b": 1}, "c": [2, 3]}'

    def test_single_quotes_to_double(self, service: StrategistService) -> None:
        """Replace single quotes with double quotes (best-effort)."""
        raw = "{'key': 'value'}"
        result = service._repair_json(raw)
        assert result == '{"key": "value"}'


# ---------------------------------------------------------------------------
# _extract_fields_via_regex
# ---------------------------------------------------------------------------


class TestExtractFieldsViaRegex:
    """Tests for :meth:`StrategistService._extract_fields_via_regex`."""

    def test_extract_success_probability(self, service: StrategistService) -> None:
        """Extract success_probability as a float."""
        text = 'Some text "success_probability": 0.75 more text'
        result = service._extract_fields_via_regex(text)
        assert result is not None
        assert result["success_probability"] == 0.75

    def test_extract_summary(self, service: StrategistService) -> None:
        """Extract summary as a string."""
        text = 'Some text "summary": "یک خلاصه فارسی" more text'
        result = service._extract_fields_via_regex(text)
        assert result is not None
        assert result["summary"] == "یک خلاصه فارسی"

    def test_extract_both_fields(self, service: StrategistService) -> None:
        """Extract both success_probability and summary."""
        text = (
            '"success_probability": 0.9 '
            '"summary": "تحلیل کامل"'
        )
        result = service._extract_fields_via_regex(text)
        assert result is not None
        assert result["success_probability"] == 0.9
        assert result["summary"] == "تحلیل کامل"

    def test_extract_no_fields(self, service: StrategistService) -> None:
        """Return None when no fields match."""
        text = "This text has no recognizable fields."
        result = service._extract_fields_via_regex(text)
        assert result is None


# ---------------------------------------------------------------------------
# _build_error_result
# ---------------------------------------------------------------------------


class TestBuildErrorResult:
    """Tests for :meth:`StrategistService._build_error_result`."""

    def test_returns_analysis_result(self, service: StrategistService) -> None:
        """Returns an ``AnalysisResult`` instance."""
        result = service._build_error_result("some raw content")
        assert isinstance(result, AnalysisResult)

    def test_success_probability_zero(self, service: StrategistService) -> None:
        """success_probability is 0.0."""
        result = service._build_error_result("some raw content")
        assert result.success_probability == 0.0

    def test_summary_is_persian_error(self, service: StrategistService) -> None:
        """summary contains the Persian error message."""
        result = service._build_error_result("some raw content")
        assert "خطا" in result.summary

    def test_raw_report_is_non_empty(self, service: StrategistService) -> None:
        """raw_report is a non-empty Persian markdown string."""
        result = service._build_error_result("some raw content")
        assert result.raw_report
        assert "خطا" in result.raw_report
        assert result.raw_report.startswith("#")


# ---------------------------------------------------------------------------
# _parse_analysis_response — integration tests
# ---------------------------------------------------------------------------


class TestParseAnalysisResponse:
    """Integration tests for the full multi-strategy pipeline."""

    def test_valid_json_with_persian_unicode(
        self, service: StrategistService
    ) -> None:
        """Parse valid JSON containing Persian text with ZWNJ and ZWJ."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.75,\n'
            '  "summary": "خلاصه فارسی با نویسه‌های یونیکد \u200c و \u200d",\n'
            '  "strengths": ["نقطه قوت اول"],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش"\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.75
        assert "خلاصه فارسی" in result.summary
        assert "\u200c" in result.summary
        assert "\u200d" in result.summary
        assert result.raw_report == "# گزارش"

    def test_json_with_trailing_comma(self, service: StrategistService) -> None:
        """Repair and parse JSON with a trailing comma."""
        raw = '{"strengths": ["a", "b",], "success_probability": 0.5, "summary": "test"}'
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.5
        assert result.strengths == ["a", "b"]

    def test_json_without_code_fences(self, service: StrategistService) -> None:
        """Parse raw JSON without any markdown fences."""
        raw = '{"success_probability": 0.85, "summary": "direct json"}'
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.85
        assert result.summary == "direct json"

    def test_json_with_text_before_and_after_fence(
        self, service: StrategistService
    ) -> None:
        """Extract and parse JSON when there is text around the code fence."""
        raw = (
            'Here is the analysis:\n\n'
            '```json\n'
            '{\n'
            '  "success_probability": 0.6,\n'
            '  "summary": "extracted from fence"\n'
            '}\n'
            '```\n'
            'End of analysis.'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.6
        assert result.summary == "extracted from fence"

    def test_malformed_text_returns_error_result(
        self, service: StrategistService
    ) -> None:
        """Completely malformed text returns the error AnalysisResult."""
        raw = "This is not JSON at all. هیچ JSON ای وجود ندارد."
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.0
        assert "خطا" in result.summary
        assert result.raw_report  # non-empty Persian error report

    def test_empty_string_returns_error_result(
        self, service: StrategistService
    ) -> None:
        """Empty string returns the error AnalysisResult."""
        result = service._parse_analysis_response("")
        assert result.success_probability == 0.0
        assert "خطا" in result.summary
        assert result.raw_report  # non-empty Persian error report

    def test_json_with_single_quotes(self, service: StrategistService) -> None:
        """Repair and parse JSON that uses single quotes."""
        raw = (
            "{'success_probability': 0.4, 'summary': 'single quoted'}"
        )
        result = service._parse_analysis_response(raw)
        # After repair, single quotes become double quotes
        assert result.success_probability == 0.4
        assert result.summary == "single quoted"

    def test_raw_report_fallback_built_from_fields(
        self, service: StrategistService
    ) -> None:
        """When raw_report is missing, _build_fallback_report is called."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.9,\n'
            '  "summary": "no raw report",\n'
            '  "strengths": ["strong"],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": ["do it"],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": []\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.9
        assert result.summary == "no raw report"
        assert result.strengths == ["strong"]
        assert result.recommendations == ["do it"]
        # raw_report should be auto-generated since it was missing
        assert result.raw_report
        # The fallback report includes the summary text in the ## خلاصه section
        assert "no raw report" in result.raw_report
        # Verify it's a proper Persian markdown report
        assert "گزارش تحلیل استراتژیک" in result.raw_report
        assert "احتمال موفقیت" in result.raw_report
        assert "نقاط قوت" in result.raw_report
        assert "توصیه" in result.raw_report


# ---------------------------------------------------------------------------
# Truncated JSON (missing closing fence)
# ---------------------------------------------------------------------------


class TestTruncatedJsonResponse:
    """Tests for truncated LLM responses where the closing ``` is missing."""

    def test_truncated_json_fence_missing_closing(
        self, service: StrategistService
    ) -> None:
        """Parse a response where the closing ``` is cut off."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.65,\n'
            '  "summary": "تحلیل truncated",\n'
            '  "strengths": ["قوت اول"],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش ناقص"\n'
            '}'
            # NOTE: no closing ``` — simulates token-limit truncation
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.65
        assert "تحلیل truncated" in result.summary
        assert result.strengths == ["قوت اول"]
        assert result.raw_report == "# گزارش ناقص"

    def test_truncated_json_no_fence_at_all(
        self, service: StrategistService
    ) -> None:
        """Parse a truncated JSON object without any markdown fences."""
        raw = (
            '{\n'
            '  "success_probability": 0.42,\n'
            '  "summary": "بخشی از خلاصه",\n'
            '  "strengths": ["نقطه قوت"],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش"\n'
            '}'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.42
        assert "بخشی از خلاصه" in result.summary
        assert result.strengths == ["نقطه قوت"]

    def test_truncated_json_with_text_before(
        self, service: StrategistService
    ) -> None:
        """Parse a truncated JSON object with leading text and no fences."""
        raw = (
            'Here is the analysis result:\n\n'
            '{\n'
            '  "success_probability": 0.88,\n'
            '  "summary": "خلاصه موفق",\n'
            '  "strengths": [],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# موفق"\n'
            '}'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.88
        assert "خلاصه موفق" in result.summary

    def test_truncated_json_only_brace_block(
        self, service: StrategistService
    ) -> None:
        """Graceful degradation: find {…} block when fence extraction fails."""
        raw = (
            'Some text before\n'
            '```json\n'
            '{\n'
            '  "success_probability": 0.33,\n'
            '  "summary": "بازیابی از brace"\n'
            '}\n'
            'Some text after with no closing fence'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.33
        assert "بازیابی از brace" in result.summary


# ---------------------------------------------------------------------------
# Persian Text with Newlines and Quotes
# ---------------------------------------------------------------------------


class TestPersianTextWithNewlines:
    """Tests for Persian text containing newlines, quotes, and special chars."""

    def test_persian_summary_with_newlines(
        self, service: StrategistService
    ) -> None:
        """Parse a summary containing Persian text with embedded newlines."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.70,\n'
            '  "summary": "خلاصه‌ای که\nدارای newline\nدر متن فارسی است",\n'
            '  "strengths": [],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش"\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.70
        assert "خلاصه‌ای که" in result.summary
        assert "دارای newline" in result.summary
        assert "در متن فارسی است" in result.summary

    def test_persian_raw_report_with_newlines(
        self, service: StrategistService
    ) -> None:
        """Parse a raw_report containing multi-line Persian markdown."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.80,\n'
            '  "summary": "خلاصه",\n'
            '  "strengths": [],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش تحلیل\\n\\n'
            '## خلاصه\\n'
            'این یک تحلیل حقوقی است\\n\\n'
            '## نقاط قوت\\n'
            '- قوت اول\\n'
            '- قوت دوم"\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.80
        assert "خلاصه" in result.summary
        assert "گزارش تحلیل" in result.raw_report
        assert "نقاط قوت" in result.raw_report
        assert "قوت اول" in result.raw_report

    def test_persian_text_with_guillemets(
        self, service: StrategistService
    ) -> None:
        """Parse Persian text containing guillemet quotation marks («»)."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.50,\n'
            '  "summary": "متن با «گیومه» فارسی",\n'
            '  "strengths": [],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش با «نقل‌قول»"\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.50
        assert "گیومه" in result.summary
        assert "نقل‌قول" in result.raw_report

    def test_persian_text_with_escaped_quotes(
        self, service: StrategistService
    ) -> None:
        """Parse Persian text containing escaped double quotes."""
        raw = (
            '```json\n'
            '{\n'
            '  "success_probability": 0.60,\n'
            '  "summary": "متن با \\"نقل قول\\" درون خود",\n'
            '  "strengths": [],\n'
            '  "weaknesses": [],\n'
            '  "risks": [],\n'
            '  "recommendations": [],\n'
            '  "applicable_laws": [],\n'
            '  "applicable_precedents": [],\n'
            '  "raw_report": "# گزارش"\n'
            '}\n'
            '```'
        )
        result = service._parse_analysis_response(raw)
        assert result.success_probability == 0.60
        assert "نقل قول" in result.summary


# ---------------------------------------------------------------------------
# _save_strategic_report — idempotency (requires DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSaveStrategicReportIdempotency:
    """Tests for :meth:`StrategistService._save_strategic_report` idempotency.

    Ensures that calling ``_save_strategic_report`` twice for the same
    conversation updates the existing record instead of raising an
    ``IntegrityError``.
    """

    @pytest.fixture
    def _user(self, db) -> "User":
        """Create a test user for conversation creation."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(
            email="strategist_test_user@example.com",
            password="test_pass",
        )

    def _make_analysis_result(
        self,
        success_probability: float,
        summary: str,
    ) -> AnalysisResult:
        """Build a minimal ``AnalysisResult`` for testing."""
        return AnalysisResult(
            success_probability=success_probability,
            summary=summary,
            strengths=[],
            weaknesses=[],
            risks=[],
            recommendations=[],
            applicable_laws=[],
            applicable_precedents=[],
            raw_report=f"# {summary}",
        )

    def test_first_call_creates_report(
        self, _user, service: StrategistService
    ) -> None:
        """First call creates a new StrategicReport."""
        from conversations.models import Conversation, StrategicReport

        conv = Conversation.objects.create(title="test", user=_user)
        result = self._make_analysis_result(0.75, "اولین تحلیل")

        service._save_strategic_report(
            conversation_id=str(conv.id),
            case_profile_data={
                "case_type": "test_case",
                "facts": {"key": "value"},
                "completeness_score": 0.8,
                "is_complete": True,
            },
            analysis_result=result,
        )

        report = StrategicReport.objects.get(conversation=conv)
        assert report.success_probability == 0.75
        assert "اولین تحلیل" in report.summary

    def test_second_call_updates_report(
        self, _user, service: StrategistService
    ) -> None:
        """Second call updates the existing report (no IntegrityError)."""
        from conversations.models import Conversation, StrategicReport

        conv = Conversation.objects.create(title="test", user=_user)

        # First call — create
        result1 = self._make_analysis_result(0.75, "تحلیل اول")
        service._save_strategic_report(
            conversation_id=str(conv.id),
            case_profile_data={
                "case_type": "test_case",
                "facts": {"key": "value"},
                "completeness_score": 0.8,
                "is_complete": True,
            },
            analysis_result=result1,
        )

        # Second call — update (should NOT raise IntegrityError)
        result2 = self._make_analysis_result(0.95, "تحلیل دوم (به‌روزرسانی)")
        service._save_strategic_report(
            conversation_id=str(conv.id),
            case_profile_data={
                "case_type": "test_case",
                "facts": {"key": "value"},
                "completeness_score": 0.8,
                "is_complete": True,
            },
            analysis_result=result2,
        )

        # Verify the report was updated (not duplicated)
        reports = StrategicReport.objects.filter(conversation=conv)
        assert reports.count() == 1
        report = reports.first()
        assert report.success_probability == 0.95
        assert "تحلیل دوم" in report.summary
        assert "تحلیل اول" not in report.summary

    def test_multiple_conversations_independent(
        self, _user, service: StrategistService
    ) -> None:
        """Reports for different conversations are independent."""
        from conversations.models import Conversation, StrategicReport

        conv_a = Conversation.objects.create(title="case A", user=_user)
        conv_b = Conversation.objects.create(title="case B", user=_user)

        result_a = self._make_analysis_result(0.5, "تحلیل A")
        result_b = self._make_analysis_result(0.9, "تحلیل B")

        service._save_strategic_report(
            conversation_id=str(conv_a.id),
            case_profile_data={
                "case_type": "case_a",
                "facts": {},
                "completeness_score": 1.0,
                "is_complete": True,
            },
            analysis_result=result_a,
        )
        service._save_strategic_report(
            conversation_id=str(conv_b.id),
            case_profile_data={
                "case_type": "case_b",
                "facts": {},
                "completeness_score": 1.0,
                "is_complete": True,
            },
            analysis_result=result_b,
        )

        assert StrategicReport.objects.count() == 2
        report_a = StrategicReport.objects.get(conversation=conv_a)
        report_b = StrategicReport.objects.get(conversation=conv_b)
        assert report_a.success_probability == 0.5
        assert report_b.success_probability == 0.9


# ---------------------------------------------------------------------------
# FactExtractor — Fact Preservation on Parse Failure (Fix A)
# ---------------------------------------------------------------------------


class TestFactExtractorFactPreservation:
    """Tests for :class:`FactExtractor` fact preservation on JSON parse failure.

    Verifies Fix A: when ``_parse_extraction_response`` encounters malformed
    JSON, it now raises ``ValueError`` instead of silently returning empty
    facts. The ``extract()`` method's ``except Exception`` handler catches
    this and preserves ``existing_profile`` facts.
    """

    def test_preserves_existing_facts_on_invalid_json(
        self, monkeypatch,
    ) -> None:
        """existing_profile facts are preserved when LLM returns bad JSON."""
        from conversations.strategist_service import FactExtractor

        # Mock the chat provider to return malformed JSON
        def mock_chat(*args, **kwargs):
            return {"content": "This is not valid JSON at all."}

        monkeypatch.setattr(
            "conversations.strategist_service.get_chat_provider",
            lambda: type("MockProvider", (), {"chat": mock_chat})(),
        )

        extractor = FactExtractor()
        existing_facts = {
            "parties": {"خريداري": "علي", "فروشنده": "محمد"},
            "claims": "الزام به تنظيم سند خودرو",
            "amount": 500000000,
        }

        result = extractor.extract(
            user_message="من خریدار هستم و آقای محمد فروشنده",
            existing_profile=existing_facts,
        )

        assert result.facts == existing_facts
        assert result.case_type == "other"
        assert result.is_ready is False
        assert result.completeness_score == 0.0

    def test_preserves_existing_facts_on_truncated_json(
        self, monkeypatch,
    ) -> None:
        """existing_profile facts are preserved when LLM returns truncated JSON."""
        from conversations.strategist_service import FactExtractor

        def mock_chat(*args, **kwargs):
            return {
                "content": (
                    '```json\n'
                    '{\n'
                    '  "case_type": "contract_dispute",\n'
                    '  "facts": {\n'
                    '    "parties": {"م": "خ'
                )
                # NOTE: Truncated mid-Persian-word -- invalid JSON
            }

        monkeypatch.setattr(
            "conversations.strategist_service.get_chat_provider",
            lambda: type("MockProvider", (), {"chat": mock_chat})(),
        )

        extractor = FactExtractor()
        existing_facts = {
            "parties": {"موجر": "کاربر", "مستاجر": "نامشخص"},
            "claims": "عدم پرداخت اجاره",
        }

        result = extractor.extract(
            user_message="مستاجر پرداخت نکرده",
            existing_profile=existing_facts,
        )

        assert result.facts == existing_facts

    def test_returns_fallback_on_llm_exception(
        self, monkeypatch,
    ) -> None:
        """existing_profile facts are preserved when LLM call itself fails."""
        from conversations.strategist_service import FactExtractor

        def mock_chat(*args, **kwargs):
            raise ConnectionError("Network error")

        monkeypatch.setattr(
            "conversations.strategist_service.get_chat_provider",
            lambda: type("MockProvider", (), {"chat": mock_chat})(),
        )

        extractor = FactExtractor()
        existing_facts = {"claims": "تخلیه ملک"}

        result = extractor.extract(
            user_message="تخلیه کنید",
            existing_profile=existing_facts,
        )

        assert result.facts == existing_facts
        assert result.case_type == "other"

    def test_uses_empty_facts_when_no_existing_profile(
        self, monkeypatch,
    ) -> None:
        """When no existing_profile and LLM returns bad JSON, facts is empty dict."""
        from conversations.strategist_service import FactExtractor

        def mock_chat(*args, **kwargs):
            return {"content": "NOT JSON"}

        monkeypatch.setattr(
            "conversations.strategist_service.get_chat_provider",
            lambda: type("MockProvider", (), {"chat": mock_chat})(),
        )

        extractor = FactExtractor()
        result = extractor.extract(
            user_message="یک پرونده دارم",
            existing_profile=None,
        )

        assert result.facts == {}
        assert result.case_type == "other"


# ---------------------------------------------------------------------------
# _build_fts_keywords -- FTS Keyword Generation (Fix B)
# ---------------------------------------------------------------------------


class TestBuildFtsKeywords:
    """Tests for :meth:`StrategicAnalyzer._build_fts_keywords`.

    Verifies Fix B: keyword generation uses word-level truncation to prevent
    Unicode breaking, includes case-type base keywords, and adds facts-derived
    terms.
    """

    def test_contract_dispute_base_keywords(self):
        """Returns contract_dispute base keywords for that case type."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={},
        )

        assert "قرارداد" in keywords
        assert "عقد" in keywords
        assert "تعهد" in keywords

    def test_includes_claims_with_word_truncation(self):
        """Claims text is included with word-level (not char-level) truncation."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        long_claims = "الزام " + " طلب " * 50
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={"claims": long_claims},
        )

        assert "الزام" in keywords
        word_count = len(keywords.split())
        assert word_count <= 30

    def test_persian_word_integrity(self):
        """Word-level truncation preserves Persian word integrity."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        claims = "الزام به تنظیم سند خودرو و مطالبه وجه التزام"
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={"claims": claims},
        )

        for word in claims.split():
            if word not in ("از", "به", "و", "در"):
                assert word in keywords or len(keywords.split()) < 20

    def test_includes_evidence_keywords(self):
        """Evidence text is included with word-level truncation."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="civil",
            facts={
                "evidence": "قرارداد کتبی مبایعه نامه و رسید بانکی",
            },
        )

        assert "قرارداد کتبی" in keywords
        assert "رسید" in keywords

    def test_includes_party_role_keywords(self):
        """Known party role keys are added as keywords."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={
                "parties": {
                    "موجر": "کاربر",
                    "مستاجر": "نامشخص",
                },
            },
        )

        assert "موجر" in keywords
        assert "مستاجر" in keywords

    def test_unknown_case_type_uses_default_keyword(self):
        """Unknown case types fall back to 'قانون' as the base keyword."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="unknown_type",
            facts={},
        )

        assert "قانون" in keywords

    def test_empty_facts_returns_base_keywords_only(self):
        """When facts dict is empty, only case-type base keywords are returned."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="family_law",
            facts={},
        )

        assert "طلاق" in keywords
        assert "مهریه" in keywords
        assert "اجاره" not in keywords

    def test_handles_evidence_as_list(self):
        """Evidence field as a list is joined into a string, not crashed."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={
                "evidence": ["سند رسمی زمین", "قرارداد مشارکت عادی"],
            },
        )

        assert "سند" in keywords
        assert "قرارداد" in keywords
        assert "زمین" in keywords

    def test_handles_claims_as_list(self):
        """Claims field as a list is joined into a string, not crashed."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={
                "claims": ["الزام به تنظیم سند", "مطالبه وجه التزام"],
            },
        )

        assert "الزام" in keywords
        assert "مطالبه" in keywords
        assert "وجه" in keywords

    def test_handles_evidence_as_string(self):
        """Evidence field as a string still works correctly (backward compat)."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={
                "evidence": "یک مدرک متنی ساده",
            },
        )

        assert "مدرک" in keywords
        assert "متنی" in keywords

    def test_handles_empty_evidence_list(self):
        """Empty evidence list does not crash."""
        from conversations.strategist_service import StrategicAnalyzer

        analyzer = StrategicAnalyzer()
        keywords = analyzer._build_fts_keywords(
            case_type="contract_dispute",
            facts={
                "evidence": [],
            },
        )

        # Should not crash and return base keywords
        assert "قرارداد" in keywords


# ---------------------------------------------------------------------------
# _parse_probability_from_risk -- Type Safety (int/float/str)
# ---------------------------------------------------------------------------


class TestParseProbabilityFromRisk:
    """Tests for :func:`_parse_probability_from_risk`.

    Verifies the function handles int, float, and string types for the
    ``success_probability`` field inside ``risk_assessment``.
    """

    def test_handles_int_value(self):
        """Integer value 70 is parsed as 0.7."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(
            {"success_probability": 70}
        )
        assert result == 0.7

    def test_handles_float_value(self):
        """Float value 0.85 is returned as-is."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(
            {"success_probability": 0.85}
        )
        assert result == 0.85

    def test_handles_string_with_percent(self):
        """String like '70 درصد - some text' is parsed to 0.7."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(
            {"success_probability": "70 درصد - دعوای مستند به سند رسمی"}
        )
        assert result == 0.7

    def test_handles_persian_digits(self):
        """Persian digit string like '۷۵' is parsed to 0.75."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(
            {"success_probability": "۷۵"}
        )
        assert result == 0.75

    def test_handles_empty_risk_assessment(self):
        """Empty risk_assessment returns 0.0."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk({})
        assert result == 0.0

    def test_handles_none_risk_assessment(self):
        """None risk_assessment returns 0.0 without crashing."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(None)  # type: ignore
        assert result == 0.0

    def test_handles_string_without_digits(self):
        """String with no digits returns 0.0."""
        from conversations.strategist_service import _parse_probability_from_risk

        result = _parse_probability_from_risk(
            {"success_probability": "نامشخص"}
        )
        assert result == 0.0
