// ── Mock @/api/conversations BEFORE importing the store ─────────────────
vi.mock('@/api/conversations', () => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  sendMessage: vi.fn(),
  sendMessageStream: vi.fn(),
  deleteConversation: vi.fn(),
  renameConversation: vi.fn(),
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
    isCreatingConversation: false,
    streamingContent: '',
    thinkingStatus: null,
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

  describe('renameConversation', () => {
    it('updates conversation title in list and activeConversation on success', async () => {
      const api = await import('@/api/conversations');
      const updated = { ...mockConversation, title: 'Renamed Title' };
      vi.mocked(api.renameConversation).mockResolvedValue(updated);

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        conversations: [mockConversation],
        activeConversation: { ...mockConversationDetail },
      });

      await useConversationStore.getState().renameConversation('conv-1', 'Renamed Title');

      expect(api.renameConversation).toHaveBeenCalledWith('conv-1', 'Renamed Title');
      const state = useConversationStore.getState();
      expect(state.conversations[0].title).toBe('Renamed Title');
      expect(state.activeConversation?.title).toBe('Renamed Title');
      expect(state.error).toBeNull();
    });

    it('sets error on failure', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.renameConversation).mockRejectedValue(new Error('Rename failed'));

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        conversations: [mockConversation],
      });

      await useConversationStore.getState().renameConversation('conv-1', 'New Title');

      const state = useConversationStore.getState();
      expect(state.error).toBe('Rename failed');
      expect(state.conversations[0].title).toBe('Questions about Chapter 5');
    });
  });

  describe('sendMessageStream — Streaming Updates', () => {
    it('adds optimistic user + temp assistant messages immediately', async () => {
      const api = await import('@/api/conversations');
      // Use a deferred pattern: capture callbacks so we can control resolution
      let capturedOnDone!: (data: { message_id: string; sources: unknown[]; token_usage: unknown }) => void;
      vi.mocked(api.sendMessageStream).mockImplementation(
        (_conversationId: string, _content: string, _onToken: (token: string) => void, onDone: (data: { message_id: string; sources: unknown[]; token_usage: unknown }) => void, _onError: (error: Error) => void) => {
          capturedOnDone = onDone;
          return new AbortController();
        },
      );

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      // Trigger sendMessageStream but don't await it yet
      const sendPromise = useConversationStore.getState().sendMessageStream('conv-1', 'Hello');

      // Check optimistic state synchronously (before onDone is called)
      const state = useConversationStore.getState();
      expect(state.isSendingMessage).toBe(true);
      expect(state.activeConversation).not.toBeNull();
      // Original 2 messages + optimistic user + temp assistant = 4
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length + 2,
      );
      const lastMsg = state.activeConversation!.messages[
        state.activeConversation!.messages.length - 1
      ];
      expect(lastMsg.role).toBe('assistant');
      expect(lastMsg.content).toBe('');
      expect(lastMsg.id).toMatch(/^temp-assistant-/);

      // Now resolve the promise by calling onDone
      capturedOnDone({
        message_id: 'real-msg-id',
        sources: [],
        token_usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30 },
      });

      // Wait for the promise to resolve
      await expect(sendPromise).resolves.toBeUndefined();
    });

    it('on done, replaces temp assistant with real message', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.sendMessageStream).mockImplementation(
        (_conversationId: string, _content: string, _onToken: (token: string) => void, onDone: (data: { message_id: string; sources: unknown[]; token_usage: unknown }) => void, _onError: (error: Error) => void) => {
          // Simulate streaming completion
          setTimeout(() => {
            onDone({
              message_id: 'real-msg-id',
              sources: [],
              token_usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30 },
            });
          }, 0);
          return new AbortController();
        },
      );

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      await useConversationStore.getState().sendMessageStream('conv-1', 'Hello');

      const state = useConversationStore.getState();
      expect(state.isSendingMessage).toBe(false);
      expect(state.streamingContent).toBe('');
      expect(state.error).toBeNull();
      // Original 2 + optimistic user + real assistant = 4
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length + 2,
      );
      const lastMsg = state.activeConversation!.messages[
        state.activeConversation!.messages.length - 1
      ];
      expect(lastMsg.id).toBe('real-msg-id');
    });

    it('on error, removes temp messages and sets error', async () => {
      const api = await import('@/api/conversations');
      vi.mocked(api.sendMessageStream).mockImplementation(
        (_conversationId: string, _content: string, _onToken: (token: string) => void, _onDone: (data: unknown) => void, onError: (error: Error) => void) => {
          // Simulate error
          setTimeout(() => {
            onError(new Error('Stream failed'));
          }, 0);
          return new AbortController();
        },
      );

      const useConversationStore = await resetStore();
      useConversationStore.setState({
        activeConversation: { ...mockConversationDetail },
      });

      await expect(
        useConversationStore.getState().sendMessageStream('conv-1', 'Hello'),
      ).rejects.toThrow('Stream failed');

      const state = useConversationStore.getState();
      expect(state.isSendingMessage).toBe(false);
      expect(state.streamingContent).toBe('');
      expect(state.error).toBe('Stream failed');
      // Messages should be back to original length (temp messages removed)
      expect(state.activeConversation!.messages).toHaveLength(
        mockConversationDetail.messages.length,
      );
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
