"""Auto-register all built-in providers.

Importing this module triggers registration so that
:func:`~providers.registry.get_embedding_provider` and
:func:`~providers.registry.get_chat_provider` can find them.
"""

from providers.registry import register_chat_provider, register_embedding_provider

# ---------------------------------------------------------------------------
# Embedding providers
# ---------------------------------------------------------------------------
from providers.gemini_embedding import GeminiEmbeddingProvider
from providers.openai_embedding import OpenAIEmbeddingProvider
from providers.ollama_embedding import OllamaEmbeddingProvider

register_embedding_provider("google", GeminiEmbeddingProvider)
register_embedding_provider("openai", OpenAIEmbeddingProvider)
register_embedding_provider("ollama", OllamaEmbeddingProvider)

# ---------------------------------------------------------------------------
# Chat providers
# ---------------------------------------------------------------------------
from providers.openai_chat import OpenAIChatProvider
from providers.gemini_chat import GeminiChatProvider
from providers.ollama_chat import OllamaChatProvider

register_chat_provider("openai", OpenAIChatProvider)
register_chat_provider("google", GeminiChatProvider)
register_chat_provider("ollama", OllamaChatProvider)
