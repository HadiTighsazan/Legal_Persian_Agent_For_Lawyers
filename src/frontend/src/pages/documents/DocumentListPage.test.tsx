import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import DocumentListPage from "./DocumentListPage";
import type { PaginatedResponse, Document } from "@/types/document";

// ── Mock the API module ───────────────────────────────────────────────────
const mockListDocuments = vi.fn();
vi.mock("@/lib/api/documents", () => ({
  listDocuments: (...args: unknown[]) => mockListDocuments(...args),
}));

// ── Helpers ────────────────────────────────────────────────────────────────

function createMockDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: "550e8400-e29b-41d4-a716-446655440000",
    title: "Test Document",
    original_filename: "test.pdf",
    file_size: 1048576,
    total_pages: 10,
    status: "completed",
    created_at: "2026-04-18T10:00:00Z",
    updated_at: "2026-04-18T10:30:00Z",
    ...overrides,
  };
}

function createPaginatedResponse(
  results: Document[],
  overrides: Partial<PaginatedResponse<Document>> = {},
): PaginatedResponse<Document> {
  return {
    count: results.length,
    next: null,
    previous: null,
    results,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <DocumentListPage />
    </MemoryRouter>,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("DocumentListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders document cards when API returns results", async () => {
    const docs = [
      createMockDocument({ id: "1", title: "Annual Report" }),
      createMockDocument({ id: "2", title: "Meeting Notes" }),
    ];
    mockListDocuments.mockResolvedValue(createPaginatedResponse(docs));

    renderPage();

    // Wait for loading to finish and cards to appear
    await waitFor(() => {
      expect(screen.getByText("Annual Report")).toBeInTheDocument();
    });
    expect(screen.getByText("Meeting Notes")).toBeInTheDocument();
  });

  it("shows empty state when API returns no documents", async () => {
    mockListDocuments.mockResolvedValue(
      createPaginatedResponse([], { count: 0 }),
    );

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText("Upload your first document"),
      ).toBeInTheDocument();
    });
  });

  it("shows skeleton cards while loading", async () => {
    // Return a promise that never resolves to keep loading state
    mockListDocuments.mockReturnValue(new Promise<never>(() => {}));

    renderPage();

    // The skeleton cards should be visible (they use animate-pulse)
    // We check for the loading container by looking for elements with
    // the animate-pulse class — the skeleton cards are rendered in a grid
    await waitFor(() => {
      // The loading state renders 3 skeleton cards inside a grid
      const skeletons = document.querySelectorAll(".animate-pulse");
      expect(skeletons.length).toBeGreaterThanOrEqual(3);
    });
  });

  it("shows error alert when API call fails", async () => {
    mockListDocuments.mockRejectedValue(new Error("Network error"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });

    // Retry button should be visible
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});
