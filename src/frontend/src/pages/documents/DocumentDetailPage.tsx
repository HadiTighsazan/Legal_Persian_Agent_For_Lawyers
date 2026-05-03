import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  getDocument,
  triggerProcessing,
  triggerEmbedding,
} from "@/lib/api/documents";
import { useProcessingStatus } from "@/hooks/useProcessingStatus";
import type { Document } from "@/types/document";
import StatusBadge from "@/components/documents/StatusBadge";
import ProcessingStatusPanel from "@/components/documents/ProcessingStatusPanel";
import DeleteDocumentDialog from "@/components/documents/DeleteDocumentDialog";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { toast } from "@/hooks/use-toast";
import {
  AlertCircle,
  ArrowLeft,
  FileText,
  Trash2,
  MessageSquare,
} from "lucide-react";

// ── Helpers (extracted from DocumentCard for reuse) ─────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const value = bytes / Math.pow(k, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ── Skeleton component for loading state ────────────────────────────────────

function DetailSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-5 w-32 rounded bg-muted" />
      <div className="space-y-2">
        <div className="h-8 w-3/4 rounded bg-muted" />
        <div className="h-5 w-1/2 rounded bg-muted" />
      </div>
      <Card>
        <CardContent className="p-5">
          <div className="grid grid-cols-2 gap-4">
            <div className="h-4 w-20 rounded bg-muted" />
            <div className="h-4 w-16 rounded bg-muted" />
            <div className="h-4 w-32 rounded bg-muted" />
            <div className="h-5 w-24 rounded-full bg-muted" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Page component ──────────────────────────────────────────────────────────

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();

  // ── State ──────────────────────────────────────────────────────────────
  const [document, setDocument] = useState<Document | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  // ── Processing status polling ──────────────────────────────────────────
  const { statusData, isPolling } = useProcessingStatus(
    documentId,
    !isLoading && document !== null && document.processing_status !== "completed",
  );

  // ── Fetch document details ─────────────────────────────────────────────
  const fetchDocument = useCallback(async () => {
    if (!documentId) return;

    setIsLoading(true);
    setError(null);

    try {
      const doc = await getDocument(documentId);
      setDocument(doc);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to load document.";
      setError(message);
      setDocument(null);
    } finally {
      setIsLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    fetchDocument();
  }, [fetchDocument]);

  // ── Handlers ───────────────────────────────────────────────────────────

  const handleBack = () => {
    navigate("/documents");
  };

  const handleStartChat = () => {
    navigate(`/conversations/new?documentId=${documentId}`);
  };

  const handleDeleteClick = () => {
    setDeleteDialogOpen(true);
  };

  const handleDocumentDeleted = () => {
    toast({
      title: "Document deleted",
      description: "The document has been permanently removed.",
    });
    navigate("/documents");
  };

  const handleStartProcessing = async () => {
    if (!documentId) return;
    try {
      await triggerProcessing(documentId);
      // Refetch document to update processing_status
      fetchDocument();
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to start processing.";
      setError(message);
    }
  };

  const handleRetry = async (_taskId: string) => {
    // Retry by re-triggering processing
    await handleStartProcessing();
  };

  const handleGenerateEmbeddings = async () => {
    if (!documentId) return;
    try {
      await triggerEmbedding(documentId);
      fetchDocument();
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to generate embeddings.";
      setError(message);
    }
  };

  // ── Render: Loading ────────────────────────────────────────────────────
  if (isLoading) {
    return <DetailSkeleton />;
  }

  // ── Render: Error ──────────────────────────────────────────────────────
  if (error && !document) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" onClick={handleBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Documents
        </Button>

        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription className="mt-1">
            <p>{error}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={fetchDocument}
            >
              Try Again
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  // ── Render: Not found ──────────────────────────────────────────────────
  if (!document) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" onClick={handleBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Documents
        </Button>

        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-center">
          <FileText className="mb-4 h-12 w-12 text-muted-foreground" />
          <h3 className="text-lg font-semibold">Document not found</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            The document you're looking for doesn't exist or has been removed.
          </p>
          <Button className="mt-4" onClick={handleBack}>
            Go to Documents
          </Button>
        </div>
      </div>
    );
  }

  // ── Render: Data ───────────────────────────────────────────────────────
  const processingStatus = document.processing_status ?? document.status;

  return (
    <div className="space-y-6">
      {/* ── Back button ──────────────────────────────────────────────── */}
      <Button variant="ghost" size="sm" onClick={handleBack}>
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Documents
      </Button>

      {/* ── Title + filename ─────────────────────────────────────────── */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{document.title}</h1>
        <p className="mt-1 text-muted-foreground">
          {document.original_filename}
        </p>
      </div>

      {/* ── Metadata section ─────────────────────────────────────────── */}
      <Card>
        <CardContent className="p-5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
            <div>
              <span className="text-muted-foreground">Size:</span>{" "}
              <span className="font-medium">
                {formatFileSize(document.file_size)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Pages:</span>{" "}
              <span className="font-medium">
                {document.total_pages !== null ? document.total_pages : "—"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Uploaded:</span>{" "}
              <span className="font-medium">
                {formatDate(document.created_at)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Status:</span>{" "}
              <StatusBadge status={processingStatus} />
            </div>
          </div>

          {/* ── Error message on document ────────────────────────────── */}
          {document.error_message && (
            <p className="mt-3 text-sm text-red-600">
              {document.error_message}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Processing Status Panel (conditional) ────────────────────── */}
      {processingStatus !== "completed" && (
        <ProcessingStatusPanel
          documentId={document.id}
          processingStatus={processingStatus}
          statusData={statusData}
          isPolling={isPolling}
          onStartProcessing={handleStartProcessing}
          onRetry={handleRetry}
          onGenerateEmbeddings={handleGenerateEmbeddings}
        />
      )}

      {/* ── Action buttons ───────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-3">
        <Button onClick={handleStartChat}>
          <MessageSquare className="mr-2 h-4 w-4" />
          Start Chat
        </Button>

        <Button
          variant="destructive"
          onClick={handleDeleteClick}
        >
          <Trash2 className="mr-2 h-4 w-4" />
          Delete
        </Button>
      </div>

      {/* ── Delete confirmation dialog ──────────────────────────────── */}
      <DeleteDocumentDialog
        documentId={document.id}
        documentTitle={document.title}
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onDeleted={handleDocumentDeleted}
      />
    </div>
  );
}
