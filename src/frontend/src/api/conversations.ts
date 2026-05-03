import { apiClient } from './axios';

// ── TypeScript Interfaces ──────────────────────────────────────────────

export interface Conversation {
  id: string;
  document_id: string;
  document_title: string;
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

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  sources: MessageSource[];
  token_usage: TokenUsage | null;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  document_id: string;
  document_title: string;
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
 * Create a new conversation for a document.
 * POST /conversations/
 */
export async function createConversation(
  documentId: string,
  title?: string,
): Promise<Conversation> {
  try {
    const body: Record<string, string> = { document_id: documentId };
    if (title !== undefined) {
      body.title = title;
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
): Promise<PaginatedConversations> {
  try {
    const params: Record<string, string | number> = { page };
    if (documentId !== undefined) {
      params.document_id = documentId;
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
 */
export async function sendMessage(
  conversationId: string,
  content: string,
): Promise<Message> {
  try {
    const { data } = await apiClient.post<Message>(
      `conversations/${conversationId}/messages/`,
      { content },
    );
    return data;
  } catch (error) {
    handleError(error);
  }
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
