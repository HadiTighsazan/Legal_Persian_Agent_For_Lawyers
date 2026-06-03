import { apiClient, normalizeBaseUrl } from './axios';

// ── TypeScript Interfaces ──────────────────────────────────────────────

export type RagMode = 'local_rag' | 'global_rag' | 'strategist' | 'action_engine';

export interface Conversation {
  id: string;
  document_id: string | null;
  document_title: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface MessageSource {
  chunk_id: string;
  page_start: number;
  page_end: number;
  content_preview?: string;
  relevance_score: number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface PartialAnswer {
  content: string;
  token_usage: TokenUsage;
  error: string | null;
}

export interface HubMetadata {
  chunks_count: number;
  sub_query: {
    fts_query: string;
    vector_query: string;
  };
  error: string | null;
  partial_answer?: string;
  partial_answer_token_usage?: TokenUsage;
  partial_answer_error?: string | null;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources: MessageSource[];
  token_usage: TokenUsage | null;
  hub_metadata?: Record<string, HubMetadata> | null;
  partial_answers?: Record<string, PartialAnswer> | null;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  document_id: string | null;
  document_title: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface PaginatedConversations {
  count: number;
  next: string | null;
  previous: string | null;
  results: Conversation[];
}

export interface DirectQueryResponse {
  answer: string;
  sources: MessageSource[];
  token_usage: TokenUsage;
}

// ── Error Handling ─────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function handleError(error: unknown): never {
  // Check for AxiosError by looking for the isAxiosError flag.
  // This works for both real AxiosError instances and test mock objects.
  const isAxiosError =
    typeof error === 'object' &&
    error !== null &&
    'isAxiosError' in error &&
    (error as Record<string, unknown>).isAxiosError === true;

  if (isAxiosError) {
    const axiosError = error as { response?: { status?: number; data?: unknown }; message?: string };
    const status = axiosError.response?.status ?? 500;
    const data = axiosError.response?.data;
    const message =
      data && typeof data === 'object' && 'message' in (data as Record<string, unknown>)
        ? String((data as Record<string, unknown>).message)
        : axiosError.message ?? 'Request failed';
    throw new ApiError(status, message, data);
  }
  throw error;
}

// ── API Functions ──────────────────────────────────────────────────────

/**
 * Create a new conversation.
 * POST /conversations/
 *
 * @param documentId - Optional document UUID. Omit for Global RAG conversations.
 * @param title - Optional human-readable title.
 */
export async function createConversation(
  documentId?: string,
  title?: string,
  mode?: RagMode,
): Promise<Conversation> {
  try {
    const body: Record<string, string> = {};
    if (documentId !== undefined) {
      body.document_id = documentId;
    }
    if (title !== undefined) {
      body.title = title;
    }
    if (mode !== undefined) {
      body.mode = mode;
    }
    const { data } = await apiClient.post<Conversation>('conversations/', body);
    return data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * List user's conversations, optionally filtered by document.
 * GET /conversations/
 */
export async function listConversations(
  documentId?: string,
  page: number = 1,
  mode?: RagMode,
): Promise<PaginatedConversations> {
  try {
    const params: Record<string, string | number> = { page };
    if (documentId !== undefined) {
      params.document_id = documentId;
    }
    if (mode !== undefined) {
      params.mode = mode;
    }
    const { data } = await apiClient.get<PaginatedConversations>('conversations/', { params });
    return data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Get conversation details with nested messages.
 * GET /conversations/{id}/
 */
export async function getConversation(
  conversationId: string,
): Promise<ConversationDetail> {
  try {
    const { data } = await apiClient.get<ConversationDetail>(
      `conversations/${conversationId}/`,
    );
    return data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Rename a conversation.
 * PATCH /conversations/{id}/
 */
export async function renameConversation(
  conversationId: string,
  title: string,
): Promise<Conversation> {
  try {
    const { data } = await apiClient.patch<Conversation>(
      `conversations/${conversationId}/`,
      { title },
    );
    return data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Delete a conversation and all its messages.
 * DELETE /conversations/{id}/
 */
export async function deleteConversation(
  conversationId: string,
): Promise<void> {
  try {
    await apiClient.delete(`conversations/${conversationId}/`);
  } catch (error) {
    handleError(error);
  }
}

/**
 * Send a message (question) in a conversation and get the assistant response.
 * POST /conversations/{id}/messages/
 *
 * @param conversationId - The conversation ID.
 * @param content - The message content.
 * @param mode - Optional RAG mode ('local_rag' or 'global_rag'). Defaults to 'local_rag'.
 */
export async function sendMessage(
  conversationId: string,
  content: string,
  mode?: RagMode,
): Promise<Message> {
  try {
    const body: Record<string, string> = { content };
    if (mode !== undefined) {
      body.mode = mode;
    }
    const { data } = await apiClient.post<Message>(
      `conversations/${conversationId}/messages/`,
      body,
    );
    return data;
  } catch (error) {
    handleError(error);
  }
}

/**
 * Send a message with SSE streaming response.
 * POST /conversations/{id}/messages/stream/
 *
 * Uses the Fetch API with ReadableStream to parse Server-Sent Events.
 *
 * @param conversationId - The conversation ID.
 * @param content - The message content.
 * @param onToken - Callback for each content token.
 * @param onDone - Callback when streaming completes, receives the final message metadata.
 * @param onError - Callback for errors.
 * @returns An AbortController to cancel the stream.
 */
export function sendMessageStream(
  conversationId: string,
  content: string,
  onToken: (token: string) => void,
  onDone: (data: { message_id: string; sources: MessageSource[]; token_usage: TokenUsage }) => void,
  onError: (error: Error) => void,
  mode?: RagMode,
  onProgress?: (status: string, reasoning?: string) => void,
): AbortController {
  const controller = new AbortController();
  const token = localStorage.getItem('access_token');

  (async () => {
    try {
      const body: Record<string, string> = { content };
      if (mode !== undefined) {
        body.mode = mode;
      }
      const baseUrl = normalizeBaseUrl(import.meta.env.VITE_API_URL || 'http://localhost:8000/api/');
      const response = await fetch(
        `${baseUrl}conversations/${conversationId}/messages/stream/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(body),
          signal: controller.signal,
        },
      );

      if (!response.ok) {
        const errorBody = await response.text().catch(() => '');
        throw new Error(`HTTP ${response.status}: ${errorBody || response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;

          try {
            const data = JSON.parse(trimmed.slice(6));

            if (data.type === 'token') {
              onToken(data.content);
            } else if (data.type === 'progress') {
              if (onProgress) {
                onProgress(data.status, data.reasoning);
              }
            } else if (data.type === 'done') {
              onDone({
                message_id: data.message_id,
                sources: data.sources,
                token_usage: data.token_usage,
              });
            } else if (data.type === 'error') {
              onError(new Error(data.message || 'Stream error'));
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return; // Cancelled, not an error
      }
      onError(error instanceof Error ? error : new Error(String(error)));
    }
  })();

  return controller;
}

/**
 * Direct query against a document without creating a conversation.
 * POST /documents/{id}/query
 */
export async function directQuery(
  documentId: string,
  question: string,
  topK?: number,
): Promise<DirectQueryResponse> {
  try {
    const body: Record<string, string | number> = { question };
    if (topK !== undefined) {
      body.top_k = topK;
    }
    const { data } = await apiClient.post<DirectQueryResponse>(
      `documents/${documentId}/query`,
      body,
    );
    return data;
  } catch (error) {
    handleError(error);
  }
}
