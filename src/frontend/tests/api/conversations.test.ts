// ── Mock @/api/axios BEFORE importing the module under test ────────────
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockPost = vi.fn();
const mockGet = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

vi.mock('@/api/axios', () => ({
  apiClient: {
    post: mockPost,
    get: mockGet,
    patch: mockPatch,
    delete: mockDelete,
  },
}));

// ── Helper: create a fake AxiosError-like object ───────────────────────
// The implementation uses axios.isAxiosError(), which checks for the
// isAxiosError property. We create plain objects that pass that check.
function createAxiosError(status: number, data: unknown): object {
  return {
    isAxiosError: true,
    response: { status, data },
    message:
      data && typeof data === 'object' && 'message' in (data as Record<string, unknown>)
        ? String((data as Record<string, unknown>).message)
        : 'Request failed',
  };
}

// ── Mock data ──────────────────────────────────────────────────────────
const mockConversation = {
  id: 'conv-1',
  document_id: 'doc-1',
  document_title: 'Test Document',
  title: 'Questions about Chapter 5',
  message_count: 3,
  created_at: '2026-04-18T10:00:00Z',
  updated_at: '2026-04-18T11:00:00Z',
};

const mockMessage: Record<string, unknown> = {
  id: 'msg-1',
  role: 'assistant',
  content: 'Chapter 5 discusses machine learning concepts.',
  sources: [
    {
      chunk_id: 'chunk-1',
      page_start: 45,
      page_end: 47,
      content_preview: 'Machine learning concepts include...',
      relevance_score: 0.92,
    },
  ],
  token_usage: {
    prompt_tokens: 3500,
    completion_tokens: 250,
    total_tokens: 3750,
  },
  created_at: '2026-04-18T10:05:15Z',
};

const mockConversationDetail = {
  ...mockConversation,
  messages: [
    {
      id: 'msg-0',
      role: 'user',
      content: 'What is discussed in chapter 5?',
      sources: [],
      token_usage: null,
      created_at: '2026-04-18T10:05:00Z',
    },
    mockMessage,
  ],
};

const mockPaginatedConversations = {
  count: 10,
  next: 'http://localhost/api/conversations/?page=2',
  previous: null,
  results: [mockConversation],
};

const mockDirectQueryResponse = {
  answer: 'The main conclusion is that...',
  sources: [
    {
      chunk_id: 'chunk-2',
      page_start: 1950,
      page_end: 1952,
      content_preview: 'In conclusion, we found that...',
      relevance_score: 0.95,
    },
  ],
  token_usage: {
    prompt_tokens: 3500,
    completion_tokens: 250,
    total_tokens: 3750,
  },
};

// ── Setup ──────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────
describe('conversations API', () => {
  describe('createConversation', () => {
    it('calls apiClient.post with conversations/ and { document_id, title }', async () => {
      mockPost.mockResolvedValueOnce({ data: mockConversation });

      const { createConversation } = await import('@/api/conversations');
      const result = await createConversation('doc-1', 'Questions about Chapter 5');

      expect(mockPost).toHaveBeenCalledWith('conversations/', {
        document_id: 'doc-1',
        title: 'Questions about Chapter 5',
      });
      expect(result).toEqual(mockConversation);
    });

    it('returns the Conversation object on success', async () => {
      mockPost.mockResolvedValueOnce({ data: mockConversation });

      const { createConversation } = await import('@/api/conversations');
      const result = await createConversation('doc-1', 'Questions about Chapter 5');

      expect(result).toEqual(mockConversation);
    });

    it('throws ApiError on 400 (validation error)', async () => {
      const error = createAxiosError(400, { error: 'validation_error', message: 'Invalid document_id' });
      mockPost.mockRejectedValue(error);

      const { createConversation, ApiError } = await import('@/api/conversations');
      await expect(createConversation('invalid-doc')).rejects.toThrow(ApiError);
      await expect(createConversation('invalid-doc')).rejects.toMatchObject({
        status: 400,
        message: 'Invalid document_id',
      });
    });

    it('throws ApiError on 403 (document not owned)', async () => {
      const error = createAxiosError(403, { error: 'permission_denied', message: 'Document does not belong to you' });
      mockPost.mockRejectedValue(error);

      const { createConversation, ApiError } = await import('@/api/conversations');
      await expect(createConversation('doc-other')).rejects.toThrow(ApiError);
      await expect(createConversation('doc-other')).rejects.toMatchObject({
        status: 403,
        message: 'Document does not belong to you',
      });
    });

    it('throws ApiError on 404 (document not found)', async () => {
      const error = createAxiosError(404, { error: 'not_found', message: 'Document does not exist' });
      mockPost.mockRejectedValue(error);

      const { createConversation, ApiError } = await import('@/api/conversations');
      await expect(createConversation('nonexistent-doc')).rejects.toThrow(ApiError);
      await expect(createConversation('nonexistent-doc')).rejects.toMatchObject({
        status: 404,
        message: 'Document does not exist',
      });
    });

    it('works without optional title', async () => {
      mockPost.mockResolvedValueOnce({ data: { ...mockConversation, title: null } });

      const { createConversation } = await import('@/api/conversations');
      const result = await createConversation('doc-1');

      expect(mockPost).toHaveBeenCalledWith('conversations/', {
        document_id: 'doc-1',
      });
      expect(result.title).toBeNull();
    });
  });

  describe('listConversations', () => {
    it('calls apiClient.get with conversations/ and params { document_id, page }', async () => {
      mockGet.mockResolvedValueOnce({ data: mockPaginatedConversations });

      const { listConversations } = await import('@/api/conversations');
      const result = await listConversations('doc-1', 2);

      expect(mockGet).toHaveBeenCalledWith('conversations/', {
        params: { document_id: 'doc-1', page: 2 },
      });
      expect(result).toEqual(mockPaginatedConversations);
    });

    it('returns PaginatedConversations on success', async () => {
      mockGet.mockResolvedValueOnce({ data: mockPaginatedConversations });

      const { listConversations } = await import('@/api/conversations');
      const result = await listConversations();

      expect(result).toEqual(mockPaginatedConversations);
    });

    it('works without any filters (no params)', async () => {
      mockGet.mockResolvedValueOnce({ data: mockPaginatedConversations });

      const { listConversations } = await import('@/api/conversations');
      await listConversations();

      expect(mockGet).toHaveBeenCalledWith('conversations/', {
        params: { page: 1 },
      });
    });

    it('works with only document_id', async () => {
      mockGet.mockResolvedValueOnce({ data: mockPaginatedConversations });

      const { listConversations } = await import('@/api/conversations');
      await listConversations('doc-1');

      expect(mockGet).toHaveBeenCalledWith('conversations/', {
        params: { document_id: 'doc-1', page: 1 },
      });
    });

    it('works with only page', async () => {
      mockGet.mockResolvedValueOnce({ data: mockPaginatedConversations });

      const { listConversations } = await import('@/api/conversations');
      await listConversations(undefined, 3);

      expect(mockGet).toHaveBeenCalledWith('conversations/', {
        params: { page: 3 },
      });
    });

    it('throws ApiError on 401', async () => {
      const error = createAxiosError(401, { error: 'authentication_failed', message: 'Invalid or expired token' });
      mockGet.mockRejectedValue(error);

      const { listConversations, ApiError } = await import('@/api/conversations');
      await expect(listConversations()).rejects.toThrow(ApiError);
      await expect(listConversations()).rejects.toMatchObject({
        status: 401,
        message: 'Invalid or expired token',
      });
    });
  });

  describe('getConversation', () => {
    it('calls apiClient.get with conversations/{id}/', async () => {
      mockGet.mockResolvedValueOnce({ data: mockConversationDetail });

      const { getConversation } = await import('@/api/conversations');
      await getConversation('conv-1');

      expect(mockGet).toHaveBeenCalledWith('conversations/conv-1/');
    });

    it('returns ConversationDetail with nested messages', async () => {
      mockGet.mockResolvedValueOnce({ data: mockConversationDetail });

      const { getConversation } = await import('@/api/conversations');
      const result = await getConversation('conv-1');

      expect(result).toEqual(mockConversationDetail);
      expect(result.messages).toHaveLength(2);
      expect(result.messages[0].role).toBe('user');
      expect(result.messages[1].role).toBe('assistant');
    });

    it('throws ApiError on 404', async () => {
      const error = createAxiosError(404, { error: 'not_found', message: 'Conversation not found' });
      mockGet.mockRejectedValue(error);

      const { getConversation, ApiError } = await import('@/api/conversations');
      await expect(getConversation('nonexistent')).rejects.toThrow(ApiError);
      await expect(getConversation('nonexistent')).rejects.toMatchObject({
        status: 404,
        message: 'Conversation not found',
      });
    });

    it('throws ApiError on 403', async () => {
      const error = createAxiosError(403, { error: 'permission_denied', message: 'Conversation belongs to another user' });
      mockGet.mockRejectedValue(error);

      const { getConversation, ApiError } = await import('@/api/conversations');
      await expect(getConversation('conv-other')).rejects.toThrow(ApiError);
      await expect(getConversation('conv-other')).rejects.toMatchObject({
        status: 403,
        message: 'Conversation belongs to another user',
      });
    });
  });

  describe('deleteConversation', () => {
    it('calls apiClient.delete with conversations/{id}/', async () => {
      mockDelete.mockResolvedValueOnce({});

      const { deleteConversation } = await import('@/api/conversations');
      await deleteConversation('conv-1');

      expect(mockDelete).toHaveBeenCalledWith('conversations/conv-1/');
    });

    it('returns void on 204', async () => {
      mockDelete.mockResolvedValueOnce({});

      const { deleteConversation } = await import('@/api/conversations');
      const result = await deleteConversation('conv-1');

      expect(result).toBeUndefined();
    });

    it('throws ApiError on 404', async () => {
      const error = createAxiosError(404, { error: 'not_found', message: 'Conversation not found' });
      mockDelete.mockRejectedValue(error);

      const { deleteConversation, ApiError } = await import('@/api/conversations');
      await expect(deleteConversation('nonexistent')).rejects.toThrow(ApiError);
      await expect(deleteConversation('nonexistent')).rejects.toMatchObject({
        status: 404,
        message: 'Conversation not found',
      });
    });

    it('throws ApiError on 403', async () => {
      const error = createAxiosError(403, { error: 'permission_denied', message: 'Conversation belongs to another user' });
      mockDelete.mockRejectedValue(error);

      const { deleteConversation, ApiError } = await import('@/api/conversations');
      await expect(deleteConversation('conv-other')).rejects.toThrow(ApiError);
      await expect(deleteConversation('conv-other')).rejects.toMatchObject({
        status: 403,
        message: 'Conversation belongs to another user',
      });
    });
  });

  describe('sendMessage', () => {
    it('calls apiClient.post with conversations/{id}/messages/ and { content }', async () => {
      mockPost.mockResolvedValueOnce({ data: mockMessage });

      const { sendMessage } = await import('@/api/conversations');
      await sendMessage('conv-1', 'What is discussed in chapter 5?');

      expect(mockPost).toHaveBeenCalledWith('conversations/conv-1/messages/', {
        content: 'What is discussed in chapter 5?',
      });
    });

    it('returns the assistant Message with sources and token_usage', async () => {
      mockPost.mockResolvedValueOnce({ data: mockMessage });

      const { sendMessage } = await import('@/api/conversations');
      const result = await sendMessage('conv-1', 'What is discussed in chapter 5?');

      expect(result.role).toBe('assistant');
      expect(result.sources).toHaveLength(1);
      expect(result.sources[0].chunk_id).toBe('chunk-1');
      expect(result.token_usage).toBeDefined();
      expect(result.token_usage?.total_tokens).toBe(3750);
    });

    it('throws ApiError on 400 (empty content)', async () => {
      const error = createAxiosError(400, { error: 'validation_error', message: 'Content cannot be empty' });
      mockPost.mockRejectedValue(error);

      const { sendMessage, ApiError } = await import('@/api/conversations');
      await expect(sendMessage('conv-1', '')).rejects.toThrow(ApiError);
      await expect(sendMessage('conv-1', '')).rejects.toMatchObject({
        status: 400,
        message: 'Content cannot be empty',
      });
    });

    it('throws ApiError on 429 (rate limit)', async () => {
      const error = createAxiosError(429, { error: 'rate_limit_exceeded', message: 'Too many requests. Please try again later.', retry_after: 60 });
      mockPost.mockRejectedValue(error);

      const { sendMessage, ApiError } = await import('@/api/conversations');
      await expect(sendMessage('conv-1', 'question')).rejects.toThrow(ApiError);
      await expect(sendMessage('conv-1', 'question')).rejects.toMatchObject({
        status: 429,
        message: 'Too many requests. Please try again later.',
      });
    });

    it('throws ApiError on 502 (RAG service error)', async () => {
      const error = createAxiosError(502, { error: 'rag_error', message: 'RAG service unavailable' });
      mockPost.mockRejectedValue(error);

      const { sendMessage, ApiError } = await import('@/api/conversations');
      await expect(sendMessage('conv-1', 'question')).rejects.toThrow(ApiError);
      await expect(sendMessage('conv-1', 'question')).rejects.toMatchObject({
        status: 502,
        message: 'RAG service unavailable',
      });
    });
  });

  describe('directQuery', () => {
    it('calls apiClient.post with documents/{id}/query and { question, top_k }', async () => {
      mockPost.mockResolvedValueOnce({ data: mockDirectQueryResponse });

      const { directQuery } = await import('@/api/conversations');
      await directQuery('doc-1', 'What is the main conclusion?', 10);

      expect(mockPost).toHaveBeenCalledWith('documents/doc-1/query', {
        question: 'What is the main conclusion?',
        top_k: 10,
      });
    });

    it('returns DirectQueryResponse with answer, sources, token_usage', async () => {
      mockPost.mockResolvedValueOnce({ data: mockDirectQueryResponse });

      const { directQuery } = await import('@/api/conversations');
      const result = await directQuery('doc-1', 'What is the main conclusion?');

      expect(result.answer).toBe('The main conclusion is that...');
      expect(result.sources).toHaveLength(1);
      expect(result.token_usage.total_tokens).toBe(3750);
    });

    it('works without optional topK (defaults to 5)', async () => {
      mockPost.mockResolvedValueOnce({ data: mockDirectQueryResponse });

      const { directQuery } = await import('@/api/conversations');
      await directQuery('doc-1', 'What is the main conclusion?');

      expect(mockPost).toHaveBeenCalledWith('documents/doc-1/query', {
        question: 'What is the main conclusion?',
      });
    });

    it('throws ApiError on 422 (document not processed)', async () => {
      const error = createAxiosError(422, { error: 'document_not_processed', message: 'Document processing is not complete' });
      mockPost.mockRejectedValue(error);

      const { directQuery, ApiError } = await import('@/api/conversations');
      await expect(directQuery('doc-1', 'question')).rejects.toThrow(ApiError);
      await expect(directQuery('doc-1', 'question')).rejects.toMatchObject({
        status: 422,
        message: 'Document processing is not complete',
      });
    });

    it('throws ApiError on 502 (RAG service error)', async () => {
      const error = createAxiosError(502, { error: 'rag_error', message: 'RAG service unavailable' });
      mockPost.mockRejectedValue(error);

      const { directQuery, ApiError } = await import('@/api/conversations');
      await expect(directQuery('doc-1', 'question')).rejects.toThrow(ApiError);
      await expect(directQuery('doc-1', 'question')).rejects.toMatchObject({
        status: 502,
        message: 'RAG service unavailable',
      });
    });
  
    describe('renameConversation', () => {
      it('calls apiClient.patch with conversations/{id}/ and { title }', async () => {
        mockPatch.mockResolvedValueOnce({ data: mockConversation });
  
        const { renameConversation } = await import('@/api/conversations');
        await renameConversation('conv-1', 'New Title');
  
        expect(mockPatch).toHaveBeenCalledWith('conversations/conv-1/', {
          title: 'New Title',
        });
      });
  
      it('returns the updated Conversation on success', async () => {
        const updated = { ...mockConversation, title: 'Updated Title' };
        mockPatch.mockResolvedValueOnce({ data: updated });
  
        const { renameConversation } = await import('@/api/conversations');
        const result = await renameConversation('conv-1', 'Updated Title');
  
        expect(result.title).toBe('Updated Title');
        expect(result).toEqual(updated);
      });
  
      it('throws ApiError on 400 (empty title)', async () => {
        const error = createAxiosError(400, { error: 'validation_error', message: 'Title cannot be empty' });
        mockPatch.mockRejectedValue(error);
  
        const { renameConversation, ApiError } = await import('@/api/conversations');
        await expect(renameConversation('conv-1', '')).rejects.toThrow(ApiError);
        await expect(renameConversation('conv-1', '')).rejects.toMatchObject({
          status: 400,
          message: 'Title cannot be empty',
        });
      });
  
      it('throws ApiError on 403 (not owned)', async () => {
        const error = createAxiosError(403, { error: 'permission_denied', message: 'Conversation belongs to another user' });
        mockPatch.mockRejectedValue(error);
  
        const { renameConversation, ApiError } = await import('@/api/conversations');
        await expect(renameConversation('conv-other', 'New Title')).rejects.toThrow(ApiError);
        await expect(renameConversation('conv-other', 'New Title')).rejects.toMatchObject({
          status: 403,
          message: 'Conversation belongs to another user',
        });
      });
  
      it('throws ApiError on 404 (not found)', async () => {
        const error = createAxiosError(404, { error: 'not_found', message: 'Conversation not found' });
        mockPatch.mockRejectedValue(error);
  
        const { renameConversation, ApiError } = await import('@/api/conversations');
        await expect(renameConversation('nonexistent', 'Title')).rejects.toThrow(ApiError);
        await expect(renameConversation('nonexistent', 'Title')).rejects.toMatchObject({
          status: 404,
          message: 'Conversation not found',
        });
      });
    });
  
    describe('sendMessageStream', () => {
      beforeEach(() => {
        // Mock localStorage for token retrieval
        vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('test-token');
      });
  
      afterEach(() => {
        vi.restoreAllMocks();
      });
  
      it('returns an AbortController', async () => {
        const { sendMessageStream } = await import('@/api/conversations');
        const controller = sendMessageStream(
          'conv-1',
          'Hello',
          vi.fn(),
          vi.fn(),
          vi.fn(),
        );
        expect(controller).toBeInstanceOf(AbortController);
      });
  
      it('reads access_token from localStorage', async () => {
        const getItemSpy = vi.spyOn(Storage.prototype, 'getItem');
  
        const { sendMessageStream } = await import('@/api/conversations');
        sendMessageStream('conv-1', 'Hello', vi.fn(), vi.fn(), vi.fn());
  
        expect(getItemSpy).toHaveBeenCalledWith('access_token');
      });
    });
  });
});
