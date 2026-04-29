"""
Unit tests for chat provider implementations.

Tests cover:
- :class:`~providers.openai_chat.OpenAIChatProvider`
- :class:`~providers.gemini_chat.GeminiChatProvider`
- :class:`~providers.ollama_chat.OllamaChatProvider`

All external HTTP/API calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


# ============================================================================
# OpenAIChatProvider Tests
# ============================================================================


@override_settings(
    OPENAI_API_KEY="test-openai-key",
    OPENAI_CHAT_MODEL="gpt-4o-mini",
    OPENAI_CHAT_MAX_TOKENS=1000,
)
class OpenAIChatProviderTests(TestCase):
    """Tests for :class:`OpenAIChatProvider`."""

    def setUp(self) -> None:
        # Import here to avoid triggering OpenAI import at module level
        from providers.openai_chat import OpenAIChatProvider
        self.provider = OpenAIChatProvider()

    @patch("providers.openai_chat.openai")
    def test_chat_returns_content_and_token_usage(self, mock_openai: MagicMock) -> None:
        """A valid chat request returns content and token_usage."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello! How can I help you?"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            mock_response
        )

        result = self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
        )

        self.assertEqual(result["content"], "Hello! How can I help you?")
        self.assertEqual(result["token_usage"]["prompt_tokens"], 10)
        self.assertEqual(result["token_usage"]["completion_tokens"], 20)
        self.assertEqual(result["token_usage"]["total_tokens"], 30)

    @patch("providers.openai_chat.openai")
    def test_chat_passes_max_tokens_and_model(self, mock_openai: MagicMock) -> None:
        """Custom max_tokens and model are forwarded to the API."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_response.usage = MagicMock(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            mock_response
        )

        self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=500,
            model="gpt-4",
        )

        mock_openai.OpenAI.return_value.chat.completions.create.assert_called_with(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=500,
        )

    @patch("providers.openai_chat.openai")
    def test_chat_api_error_raises(self, mock_openai: MagicMock) -> None:
        """API error propagates the exception."""
        mock_openai.OpenAI.return_value.chat.completions.create.side_effect = Exception(
            "API error"
        )

        with self.assertRaises(Exception):
            self.provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
            )


# ============================================================================
# GeminiChatProvider Tests
# ============================================================================


@override_settings(
    GOOGLE_API_KEY="test-gemini-key",
    GEMINI_CHAT_MODEL="gemini-2.0-flash",
)
class GeminiChatProviderTests(TestCase):
    """Tests for :class:`GeminiChatProvider`."""

    def setUp(self) -> None:
        from providers.gemini_chat import GeminiChatProvider
        self.provider = GeminiChatProvider()

    @patch("providers.gemini_chat.requests.post")
    def test_chat_returns_content(self, mock_post: MagicMock) -> None:
        """A valid chat request returns content from Gemini response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Gemini!"}],
                    },
                },
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "totalTokenCount": 30,
            },
        }
        mock_post.return_value = mock_response

        result = self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
        )

        self.assertEqual(result["content"], "Hello from Gemini!")
        self.assertEqual(result["token_usage"]["prompt_tokens"], 10)
        self.assertEqual(result["token_usage"]["completion_tokens"], 20)
        self.assertEqual(result["token_usage"]["total_tokens"], 30)

    @patch("providers.gemini_chat.requests.post")
    def test_chat_converts_system_message(self, mock_post: MagicMock) -> None:
        """System message is placed in system_instruction field."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "OK"}],
                    },
                },
            ],
        }
        mock_post.return_value = mock_response

        self.provider.chat(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi"},
            ],
        )

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        self.assertIn("system_instruction", payload)
        self.assertEqual(
            payload["system_instruction"]["parts"][0]["text"],
            "You are a helpful assistant.",
        )

    @patch("providers.gemini_chat.requests.post")
    def test_chat_converts_assistant_to_model_role(self, mock_post: MagicMock) -> None:
        """Assistant messages are converted to 'model' role for Gemini."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "OK"}],
                    },
                },
            ],
        }
        mock_post.return_value = mock_response

        self.provider.chat(
            messages=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
        )

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        contents = payload["contents"]
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")

    @patch("providers.gemini_chat.requests.post")
    def test_chat_passes_max_tokens(self, mock_post: MagicMock) -> None:
        """max_tokens is mapped to maxOutputTokens in generationConfig."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "OK"}],
                    },
                },
            ],
        }
        mock_post.return_value = mock_response

        self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=500,
        )

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        self.assertEqual(
            payload["generationConfig"]["maxOutputTokens"],
            500,
        )

    @patch("providers.gemini_chat.requests.post")
    def test_chat_api_error_raises(self, mock_post: MagicMock) -> None:
        """API error propagates the exception."""
        mock_post.side_effect = Exception("API error")

        with self.assertRaises(Exception):
            self.provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
            )


# ============================================================================
# OllamaChatProvider Tests
# ============================================================================


@override_settings(
    OLLAMA_BASE_URL="http://localhost:11434",
    OLLAMA_CHAT_MODEL="llama3",
)
class OllamaChatProviderTests(TestCase):
    """Tests for :class:`OllamaChatProvider`."""

    def setUp(self) -> None:
        from providers.ollama_chat import OllamaChatProvider
        self.provider = OllamaChatProvider()

    @patch("providers.ollama_chat.requests.post")
    def test_chat_returns_content_and_token_usage(self, mock_post: MagicMock) -> None:
        """A valid chat request returns content and token_usage."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello from Ollama!"},
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        mock_post.return_value = mock_response

        result = self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
        )

        self.assertEqual(result["content"], "Hello from Ollama!")
        self.assertEqual(result["token_usage"]["prompt_tokens"], 10)
        self.assertEqual(result["token_usage"]["completion_tokens"], 20)
        self.assertEqual(result["token_usage"]["total_tokens"], 30)

    @patch("providers.ollama_chat.requests.post")
    def test_chat_passes_max_tokens(self, mock_post: MagicMock) -> None:
        """max_tokens is mapped to options.num_predict."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "OK"},
        }
        mock_post.return_value = mock_response

        self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=500,
        )

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        self.assertEqual(payload["options"]["num_predict"], 500)

    @patch("providers.ollama_chat.requests.post")
    def test_chat_passes_custom_model(self, mock_post: MagicMock) -> None:
        """Custom model name is forwarded."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "OK"},
        }
        mock_post.return_value = mock_response

        self.provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="llama3:70b",
        )

        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        self.assertEqual(payload["model"], "llama3:70b")

    @patch("providers.ollama_chat.requests.post")
    def test_chat_api_error_raises(self, mock_post: MagicMock) -> None:
        """API error propagates the exception."""
        mock_post.side_effect = Exception("API error")

        with self.assertRaises(Exception):
            self.provider.chat(
                messages=[{"role": "user", "content": "Hi"}],
            )
