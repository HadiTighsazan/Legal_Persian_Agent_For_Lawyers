import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { listDocuments } from "@/lib/api/documents";
import type { Document } from "@/types/document";
import DocumentCard from "@/components/documents/DocumentCard";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, FileText, Search, Upload } from "lucide-react";

const PAGE_SIZE = 20;

/**
 * A simple skeleton card used during the loading state.
 */
function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-lg border bg-card p-5 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 space-y-2">
          <div className="h-5 w-3/4 rounded bg-muted" />
          <div className="h-4 w-1/2 rounded bg-muted" />
        </div>
        <div className="h-5 w-20 rounded-full bg-muted" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="h-4 w-16 rounded bg-muted" />
        <div className="h-4 w-12 rounded bg-muted" />
        <div className="col-span-2 h-4 w-32 rounded bg-muted" />
      </div>
    </div>
  );
}

export default function DocumentListPage() {
  const navigate = useNavigate();

  // ── State ──────────────────────────────────────────────────────────────
  const [documents, setDocuments] = useState<Document[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ref to track if this is the initial mount (skip debounce on mount)
  const isInitialMount = useRef(true);

  // ── Derived values ─────────────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  // ── Data fetching ──────────────────────────────────────────────────────
  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await listDocuments({
        page: currentPage,
        page_size: PAGE_SIZE,
        search: searchQuery || undefined,
        status: statusFilter || undefined,
      });

      setDocuments(response.results);
      setTotalCount(response.count);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load documents.";
      setError(message);
      setDocuments([]);
    } finally {
      setIsLoading(false);
    }
  }, [currentPage, searchQuery, statusFilter]);

  // Fetch on mount and when page/status changes
  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments, currentPage, statusFilter]);

  // ── Debounced search ───────────────────────────────────────────────────
  useEffect(() => {
    // Skip debounce on initial mount — fetchDocuments is already called above
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    const timer = setTimeout(() => {
      setCurrentPage(1); // Reset to page 1 on search
      // fetchDocuments will be triggered by the currentPage change effect
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  // ── Handlers ───────────────────────────────────────────────────────────
  const handlePreviousPage = () => {
    if (currentPage > 1) {
      setCurrentPage((prev) => prev - 1);
    }
  };

  const handleNextPage = () => {
    if (currentPage < totalPages) {
      setCurrentPage((prev) => prev + 1);
    }
  };

  const handleRetry = () => {
    fetchDocuments();
  };

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* ── Page Header ──────────────────────────────────────────────── */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
        <p className="mt-1 text-muted-foreground">
          Browse and manage your uploaded documents.
        </p>
      </div>

      {/* ── Search & Filter Bar ───────────────────────────────────────── */}
      <div className="flex flex-col gap-4 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search documents by title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:w-44"
        >
          <option value="">All Statuses</option>
          <option value="completed">Completed</option>
          <option value="processing">Processing</option>
          <option value="failed">Failed</option>
          <option value="uploaded">Uploaded</option>
        </select>
      </div>

      {/* ── Content Area ─────────────────────────────────────────────── */}
      {isLoading && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!isLoading && error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription className="mt-1">
            <p>{error}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={handleRetry}
            >
              Try Again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {!isLoading && !error && documents.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-center">
          <FileText className="mb-4 h-12 w-12 text-muted-foreground" />
          <h3 className="text-lg font-semibold">No documents yet</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Upload your first document to get started.
          </p>
          <Button
            className="mt-4"
            onClick={() => navigate("/documents/upload")}
          >
            <Upload className="mr-2 h-4 w-4" />
            Upload your first document
          </Button>
        </div>
      )}

      {!isLoading && !error && documents.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {documents.map((doc) => (
              <DocumentCard key={doc.id} document={doc} />
            ))}
          </div>

          {/* ── Pagination ──────────────────────────────────────────────── */}
          <div className="flex items-center justify-center gap-4 pt-2">
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage <= 1}
              onClick={handlePreviousPage}
            >
              Previous
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage >= totalPages}
              onClick={handleNextPage}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
