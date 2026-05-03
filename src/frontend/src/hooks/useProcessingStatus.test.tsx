import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ProcessingStatusResponse } from "@/types/document";

// ── Mock the API module BEFORE importing the hook ─────────────────────────
const mockGetProcessingStatus = vi.fn();

vi.mock("@/lib/api/documents", () => ({
  getProcessingStatus: (...args: unknown[]) => mockGetProcessingStatus(...args),
}));

// ── Import the hook AFTER the mock is set up ──────────────────────────────
import { useProcessingStatus } from "./useProcessingStatus";

// ── Helpers ────────────────────────────────────────────────────────────────

function createProcessingStatus(
  overrides: Partial<ProcessingStatusResponse> = {},
): ProcessingStatusResponse {
  return {
    document_id: "test-id",
    status: "completed",
    progress: 100,
    tasks: [
      {
        task_type: "extract",
        status: "completed",
        progress: 100,
        error_message: null,
      },
    ],
    ...overrides,
  };
}

// ── Test component ─────────────────────────────────────────────────────────

function TestComponent({
  documentId,
  enabled,
}: {
  documentId: string | undefined;
  enabled: boolean;
}) {
  const { statusData, isPolling } = useProcessingStatus(documentId, enabled);

  return (
    <div>
      <span data-testid="status">{statusData?.status ?? "null"}</span>
      <span data-testid="polling">{String(isPolling)}</span>
      <span data-testid="progress">{statusData?.progress ?? 0}</span>
    </div>
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("useProcessingStatus hook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops polling after status becomes completed", async () => {
    // First call returns "processing", subsequent calls return "completed"
    mockGetProcessingStatus
      .mockResolvedValueOnce(
        createProcessingStatus({ status: "processing", progress: 50 }),
      )
      .mockResolvedValue(
        createProcessingStatus({ status: "completed", progress: 100 }),
      );

    render(
      <MemoryRouter>
        <TestComponent documentId="test-id" enabled={true} />
      </MemoryRouter>,
    );

    // Wait for the first poll (immediate) to complete (processing)
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("processing");
    });

    // Advance time by 3 seconds to trigger the next poll
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    // Wait for the second poll to return "completed"
    await waitFor(() => {
      expect(screen.getByTestId("status").textContent).toBe("completed");
    });

    // After status is completed, isPolling should be false
    expect(screen.getByTestId("polling").textContent).toBe("false");
  });

  it("does not poll when documentId is undefined", () => {
    render(
      <MemoryRouter>
        <TestComponent documentId={undefined} enabled={true} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("status").textContent).toBe("null");
    expect(screen.getByTestId("polling").textContent).toBe("false");
  });

  it("does not poll when enabled is false", () => {
    render(
      <MemoryRouter>
        <TestComponent documentId="test-id" enabled={false} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("status").textContent).toBe("null");
    expect(screen.getByTestId("polling").textContent).toBe("false");
  });
});
