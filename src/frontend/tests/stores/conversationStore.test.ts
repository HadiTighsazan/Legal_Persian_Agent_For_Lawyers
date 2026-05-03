// ── Mock @/api/conversations BEFORE importing the store ─────────────────
vi.mock('@/api/conversations', () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  sendMessage: vi.fn(),
  deleteConversation: vi.fn(),
}));

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
    {
      id: 'msg-1',
      role: 'assistant',
      content: 'Chapter 5 discusses machine learning concepts.',
      sources: [
        {
          chunk_id: 'chunk-1',
          page_start: 45,
          page_end: 47,
          content_preview: '...',
          relevance_score: 0.92,
        },
      ],
      token_usage: { prompt_tokens: 3500, completion_tokens: 250, total_tokens: 3750 },
      created_at: '2026-04-18T10:05:15Z',
    },
  ],
};

const mockAssistantMessage = {
  id: 'msg-2',
  role: 'assistant',
  content: 'Here is the answer to your question.',
  sources: [],
  token_usage: null,
  created_at: '2026-04-18T10:10:00Z',
};

const mockPaginatedConversations = {
  count: 10,
  next: 'http://localhost/api/conversations/?page=2',
  previous: null,
  results: [mockConversation],
};

// ── Setup ──────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Helper to get a fresh store ────────────────────────────────────────
async function resetStore() {
  const { useConversationStore } = await import('@/stores/conversationStore');
  useConversationStore.setState({
    conversations: [],
    activeConversation: null,
    isLoadingConversations: false,
    isLoadingMessages: false,
    isSendingMessage: false,
    error: null,
  });
  return useConversationStore;
}

// ── Tests ──────────────────────────────────────────────────────────────
describe('ConversationStore', () => {
  describe('fetchConversations', () => {
    it('sets conversations and clears loading/error on success', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.listConversations).mockResolvedValue(mockPaginatedConversations);

      const useConversationStore = await resetStore();
      await useConversationStore.getState().fetchConversations('doc-1');

      expect(api.listConversations).toHaveBeenCalledWith('doc-1');
      const state = useConversationStore.getState();
      expect(state.conversations).toEqual(mockPaginatedConversations.results);
      expect(state.isLoadingConversations).toBe(false);
      expect(state.error).toBeNull();
    });

    it('sets error and clears loading on failure', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.listConversations).mockRejectedValue(new Error('Failed to fetch'));

      const useConversationStore = await resetStore();
      await useConversationStore.getState().fetchConversations('doc-1');

      const state = useConversationStore.getState();
      expect(state.error).toBe('Failed to fetch');
      expect(state.isLoadingConversations).toBe(false);
      expect(state.conversations).toEqual([]);
    });
  });

  describe('createConversation', () => {
    it('appends new conversation to list on success', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.createConversation).mockResolvedValue(mockConversation);

      const useConversationStore = await resetStore();
      const result = await useConversationStore.getState().createConversation('doc-1', 'Questions about Chapter 5');

      expect(api.createConversation).toHaveBeenCalledWith('doc-1', 'Questions about Chapter 5');
      expect(result).toEqual(mockConversation);
      const state = useConversationStore.getState();
      expect(state.conversations).toHaveLength(1);
      expect(state.conversations[0]).toEqual(mockConversation);
    });

    it('propagates error without modifying list', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.createConversation).mockRejectedValue(new Error('Creation failed'));

      const useConversationStore = await resetStore();
      await expect(
        useConversationStore.getState().createConversation('doc-1'),
      ).rejects.toThrow('Creation failed');

      const state = useConversationStore.getState();
      expect(state.conversations).toEqual([]);
    });
  });

  describe('loadConversation', () => {
    it('sets activeConversation and clears loading/error on success', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.getConversation).mockResolvedValue(mockConversationDetail);

      const useConversationStore = await resetStore();
      await useConversationStore.getState().loadConversation('conv-1');

      expect(api.getConversation).toHaveBeenCalledWith('conv-1');
      const state = useConversationStore.getState();
      expect(state.activeConversation).toEqual(mockConversationDetail);
      expect(state.isLoadingMessages).toBe(false);
      expect(state.error).toBeNull();
    });

    it('sets error and clears loading on failure', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.getConversation).mockRejectedValue(new Error('Conversation not found'));

      const useConversationStore = await resetStore();
      await useConversationStore.getState().loadConversation('conv-1');

      const state = useConversationStore.getState();
      expect(state.error).toBe('Conversation not found');
      expect(state.isLoadingMessages).toBe(false);
      expect(state.activeConversation).toBeNull();
    });
  });

  describe('sendMessage — Optimistic Update', () => {
    it('appends optimistic user message immediately with temp id', async () => {
      const api = await import('@/api/conversations');
      // Use a deferred promise so we can control resolution
      let resolvePromise!: (value: unknown) => void;
      vi.mocked(api.sendMessage).mockReturnValue(
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      // Trigger sendMessage but don't await it yet
      const sendPromise = useConversationStore.getState().sendMessage('conv-1', 'Hello');

      // Check state synchronously — optimistic update should be applied before await
      const state = useConversationStore.getState();
      expect(state.activeConversation).not.toBeNull();
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length + 1,
      );
      const lastMessage = state.activeConversation!.messages[
        state.activeConversation!.messages.length - 1
      ];
      expect(lastMessage.role).toBe('user');
      expect(lastMessage.content).toBe('Hello');
      expect(lastMessage.id).toMatch(/^temp-/);
      expect(state.isSendingMessage).toBe(true);

      // Cleanup: resolve the promise to avoid hanging
      resolvePromise(mockAssistantMessage);
      await sendPromise;
    });

    it('on success, replaces optimistic message with real user message + appends assistant response', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.sendMessage).mockResolvedValue(mockAssistantMessage);

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      await useConversationStore.getState().sendMessage('conv-1', 'Hello');

      const state = useConversationStore.getState();
      expect(state.activeConversation).not.toBeNull();
      // Original 2 messages + optimistic user (now with real id) + assistant response = 4
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length + 2,
      );
      // The last message should be the assistant response
      const lastMessage = state.activeConversation!.messages[
        state.activeConversation!.messages.length - 1
      ];
      expect(lastMessage.role).toBe('assistant');
      expect(lastMessage.content).toBe('Here is the answer to your question.');
      expect(lastMessage.id).toBe('msg-2');
      expect(state.isSendingMessage).toBe(false);
      expect(state.error).toBeNull();
    });

    it('on error, removes optimistic message and sets error', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.sendMessage).mockRejectedValue(new Error('Send failed'));

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      await useConversationStore.getState().sendMessage('conv-1', 'Hello');

      const state = useConversationStore.getState();
      expect(state.activeConversation).not.toBeNull();
      // Messages should be back to original length
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length,
      );
      expect(state.error).toBe('Send failed');
      expect(state.isSendingMessage).toBe(false);
    });

    it('isSendingMessage toggles correctly through the lifecycle', async () => {
      const api = await import('@/api/conversations');
      let resolvePromise!: (value: unknown) => void;
      vi.mocked(api.sendMessage).mockReturnValue(
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      // Before sending
      expect(useConversationStore.getState().isSendingMessage).toBe(false);

      // Start sending (don't await)
      const sendPromise = useConversationStore.getState().sendMessage('conv-1', 'Hello');

      // During request
      expect(useConversationStore.getState().isSendingMessage).toBe(true);

      // Resolve
      resolvePromise(mockAssistantMessage);
      await sendPromise;

      // After resolve
      expect(useConversationStore.getState().isSendingMessage).toBe(false);
    });
  });

  describe('deleteConversation', () => {
    it('removes conversation from list and clears activeConversation if deleted', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.deleteConversation).mockResolvedValue(undefined);

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        conversations: [mockConversation, { ...mockConversation, id: 'conv-2' }],
        activeConversation: { ...mockConversationDetail },
      });

      await useConversationStore.getState().deleteConversation('conv-1');

      expect(api.deleteConversation).toHaveBeenCalledWith('conv-1');
      const state = useConversationStore.getState();
      expect(state.conversations).toHaveLength(1);
      expect(state.conversations[0].id).toBe('conv-2');
      expect(state.activeConversation).toBeNull();
    });

    it('sets error on failure', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.deleteConversation).mockRejectedValue(new Error('Delete failed'));

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        conversations: [mockConversation],
      });

      await useConversationStore.getState().deleteConversation('conv-1');

      const state = useConversationStore.getState();
      expect(state.error).toBe('Delete failed');
      expect(state.conversations).toHaveLength(1);
    });
  });

  describe('clearActiveConversation / clearError', () => {
    it('clearActiveConversation sets activeConversation to null', async () => {
      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      useConversationStore.getState().clearActiveConversation();

      const state = useConversationStore.getState();
      expect(state.activeConversation).toBeNull();
    });

    it('clearError sets error to null', async () => {
      const useConversationStore = await resetStore();
      useConversationStore.setState({ error: 'Some error' });

      useConversationStore.getState().clearError();

      const state = useConversationStore.getState();
      expect(state.error).toBeNull();
    });
  });
});
