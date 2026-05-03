import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import DocumentDetailPage from "./DocumentDetailPage";
import type { Document, ProcessingStatusResponse } from "@/types/document";

// ── Mock the API module ───────────────────────────────────────────────────
const mockGetDocument = vi.fn();
const mockGetProcessingStatus = vi.fn();
const mockDeleteDocument = vi.fn();
const mockTriggerProcessing = vi.fn();
const mockTriggerEmbedding = vi.fn();

vi.mock("@/lib/api/documents", () => ({
  getDocument: (...args: unknown[]) => mockGetDocument(...args),
  getProcessingStatus: (...args: unknown[]) => mockGetProcessingStatus(...args),
  deleteDocument: (...args: unknown[]) => mockDeleteDocument(...args),
  triggerProcessing: (...args: unknown[]) => mockTriggerProcessing(...args),
  triggerEmbedding: (...args: unknown[]) => mockTriggerEmbedding(...args),
}));

// ── Mock the useProcessingStatus hook ─────────────────────────────────────
const mockUseProcessingStatus = vi.fn();

vi.mock("@/hooks/useProcessingStatus", () => ({
  useProcessingStatus: (...args: unknown[]) => mockUseProcessingStatus(...args),
}));

// ── Helpers ────────────────────────────────────────────────────────────────

function createMockDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: "550e8400-e29b-41d4-a716-446655440000",
    title: "Annual Report",
    original_filename: "annual-report.pdf",
    file_size: 2097152,
    total_pages: 42,
    status: "completed",
    processing_status: "completed",
    created_at: "2026-04-18T10:00:00Z",
    updated_at: "2026-04-18T10:30:00Z",
    mime_type: "application/pdf",
    error_message: null,
    chunks_count: 15,
    ...overrides,
  };
}

function createProcessingStatus(
  overrides: Partial<ProcessingStatusResponse> = {},
): ProcessingStatusResponse {
  return {
    document_id: "550e8400-e29b-41d4-a716-446655440000",
    status: "completed",
    progress: 100,
    tasks: [
      {
        task_type: "extract",
        status: "completed",
        progress: 100,
        error_message: null,
      },
      {
        task_type: "chunk",
        status: "completed",
        progress: 100,
        error_message: null,
      },
    ],
    ...overrides,
  };
}

function renderPage(documentId = "550e8400-e29b-41d4-a716-446655440000") {
  return render(
    <MemoryRouter initialEntries={[`/documents/${documentId}`]}>
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="/documents" element={<div>Documents List Page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: hook returns idle state
    mockUseProcessingStatus.mockReturnValue({
      statusData: null,
      isPolling: false,
      error: null,
    });
  });

  // ── Smoke test: renders completed document ────────────────────────────
  it("renders detail page with mocked completed document", async () => {
    const doc = createMockDocument();
    mockGetDocument.mockResolvedValue(doc);

    renderPage();

    // Wait for the title to appear
    await waitFor(() => {
      expect(screen.getByText("Annual Report")).toBeInTheDocument();
    });

    // Filename subtitle
    expect(screen.getByText("annual-report.pdf")).toBeInTheDocument();

    // Metadata
    expect(screen.getByText("2.0 MB")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Apr 18, 2026")).toBeInTheDocument();

    // Status badge
    expect(screen.getByText("Completed")).toBeInTheDocument();

    // Action buttons
    expect(
      screen.getByRole("button", { name: /start chat/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete/i })).toBeInTheDocument();

    // ProcessingStatusPanel should be hidden (status is completed)
    expect(
      screen.queryByText("Processing Status"),
    ).not.toBeInTheDocument();
  });

  // ── Shows loading skeleton initially ──────────────────────────────────
  it("shows loading skeleton while fetching document", async () => {
    // Return a promise that never resolves to keep loading state
    mockGetDocument.mockReturnValue(new Promise<never>(() => {}));

    renderPage();

    // The skeleton uses animate-pulse
    await waitFor(() => {
      const skeletons = document.querySelectorAll(".animate-pulse");
      expect(skeletons.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Shows error alert when fetch fails ────────────────────────────────
  it("shows error alert when document fetch fails", async () => {
    mockGetDocument.mockRejectedValue(new Error("Failed to load"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Failed to load")).toBeInTheDocument();
    });

    // Retry button should be visible
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  // ── Shows not found state when document is null after error ───────────
  it("shows not found message when document is null", async () => {
    mockGetDocument.mockResolvedValue(null);

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText("Document not found"),
      ).toBeInTheDocument();
    });
  });

  // ── Shows processing status panel when document is processing ─────────
  it("shows processing status panel when document is processing", async () => {
    const doc = createMockDocument({
      processing_status: "processing",
      status: "processing",
    });
    mockGetDocument.mockResolvedValue(doc);

    // Mock the hook to return processing data
    mockUseProcessingStatus.mockReturnValue({
      statusData: createProcessingStatus({ status: "processing" }),
      isPolling: true,
      error: null,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Annual Report")).toBeInTheDocument();
    });

    // Processing Status panel should be visible
    expect(screen.getByText("Processing Status")).toBeInTheDocument();
  });
});
