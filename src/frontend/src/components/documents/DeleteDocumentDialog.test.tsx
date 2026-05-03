import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeleteDocumentDialog from "./DeleteDocumentDialog";

// ── Mock the API module ───────────────────────────────────────────────────
const mockDeleteDocument = vi.fn();

vi.mock("@/lib/api/documents", () => ({
  deleteDocument: (...args: unknown[]) => mockDeleteDocument(...args),
}));

// ── Mock the toast hook ───────────────────────────────────────────────────
const mockToast = vi.fn();
vi.mock("@/hooks/use-toast", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

// ── Helpers ────────────────────────────────────────────────────────────────

const defaultProps = {
  documentId: "550e8400-e29b-41d4-a716-446655440000",
  documentTitle: "Annual Report",
  open: true,
  onOpenChange: vi.fn(),
  onDeleted: vi.fn(),
};

function renderDialog(props: Partial<typeof defaultProps> = {}) {
  return render(
    <DeleteDocumentDialog {...defaultProps} {...props} />,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("DeleteDocumentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Smoke test: dialog renders with title in confirmation text ─────────
  it("renders with title and confirmation text", () => {
    renderDialog();

    expect(screen.getByText("Delete Document")).toBeInTheDocument();
    expect(
      screen.getByText(/Are you sure you want to delete/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Annual Report")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /cancel/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /delete/i }),
    ).toBeInTheDocument();
  });

  // ── Interaction test: clicking Cancel closes dialog ────────────────────
  it("calls onOpenChange(false) when Cancel is clicked", async () => {
    const onOpenChange = vi.fn();
    renderDialog({ onOpenChange });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  // ── Interaction test: clicking Delete calls deleteDocument once ────────
  it("calls deleteDocument and onDeleted on successful deletion", async () => {
    mockDeleteDocument.mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const onOpenChange = vi.fn();
    renderDialog({ onDeleted, onOpenChange });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(mockDeleteDocument).toHaveBeenCalledTimes(1);
      expect(mockDeleteDocument).toHaveBeenCalledWith(
        "550e8400-e29b-41d4-a716-446655440000",
      );
    });

    expect(onDeleted).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  // ── Interaction test: shows spinner and disables buttons while deleting ─
  it("shows spinner and disables buttons while deleting", async () => {
    // Return a promise that never resolves to keep loading state
    mockDeleteDocument.mockReturnValue(new Promise<never>(() => {}));

    renderDialog();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    // Wait for the spinner to appear
    await waitFor(() => {
      expect(document.querySelector(".animate-spin")).toBeInTheDocument();
    });

    // Both buttons should be disabled
    const cancelButton = screen.getByRole("button", { name: /cancel/i });
    const deleteButton = screen.getByRole("button", { name: /delete/i });

    expect(cancelButton).toBeDisabled();
    expect(deleteButton).toBeDisabled();
  });

  // ── Error handling: shows error toast on failure ──────────────────────
  it("shows error toast when deletion fails", async () => {
    mockDeleteDocument.mockRejectedValue(new Error("Network error"));
    const onDeleted = vi.fn();
    const onOpenChange = vi.fn();
    renderDialog({ onDeleted, onOpenChange });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith({
        variant: "destructive",
        title: "Error",
        description: "Network error",
      });
    });

    // Dialog should close even on error
    expect(onOpenChange).toHaveBeenCalledWith(false);
    // onDeleted should NOT be called on error
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
