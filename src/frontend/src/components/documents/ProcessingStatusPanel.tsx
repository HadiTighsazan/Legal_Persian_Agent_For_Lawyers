import type { ProcessingStatusResponse } from "@/types/document";
import StatusBadge from "@/components/documents/StatusBadge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";

interface ProcessingStatusPanelProps {
  documentId: string;
  /** The document's `processing_status` field — used for display in the panel */
  processingStatus: string;
  /** The document's `status` field — used for action-button visibility logic */
  documentStatus: string;
  statusData: ProcessingStatusResponse | null;
  isPolling: boolean;
  onStartProcessing: () => void;
  onRetry: (taskId: string) => void;
  onGenerateEmbeddings: () => void;
}

/**
 * Human-readable labels for each task type.
 */
const TASK_TYPE_LABELS: Record<string, string> = {
  extract: "Extract Text",
  chunk: "Chunk Document",
  embed: "Generate Embeddings",
};

const DEFAULT_TASK_LABEL = "Unknown Task";

/**
 * Per-task progress rows with status badges and action buttons.
 *
 * Hidden entirely when `processingStatus === 'completed'`.
 */
export default function ProcessingStatusPanel({
  processingStatus,
  documentStatus,
  statusData,
  isPolling,
  onStartProcessing,
  onRetry,
  onGenerateEmbeddings,
}: ProcessingStatusPanelProps) {
  // ── Hidden when processing is fully complete ───────────────────────────
  if (processingStatus === "completed") {
    return null;
  }

  // ── Loading state ─────────────────────────────────────────────────────
  if (isPolling && !statusData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Processing Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Checking processing status...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  // ── No status data yet ────────────────────────────────────────────────
  if (!statusData) {
    return null;
  }

  // ── Determine which action buttons to show ────────────────────────────
  // Show "Start Processing" only when:
  //   1. The document's upload lifecycle `status` is `'uploaded'` (i.e. it has
  //      been uploaded but processing has never been triggered), AND
  //   2. The pipeline `processing_status` is NOT already `'processing'` or
  //      `'completed'` (to avoid showing the button while the pipeline is
  //      actively running or already finished).
  const showStartProcessing =
    documentStatus === "uploaded" &&
    processingStatus !== "processing" &&
    processingStatus !== "completed";
  const showRetry = processingStatus === "failed";
  const showGenerateEmbeddings =
    processingStatus === "completed" && statusData.tasks.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Processing Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* ── Per-task rows ──────────────────────────────────────────── */}
        {statusData.tasks.map((task) => (
          <div key={task.task_type} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
                {TASK_TYPE_LABELS[task.task_type] ?? DEFAULT_TASK_LABEL}
              </span>
              <StatusBadge status={task.status} />
            </div>

            <Progress value={task.progress} className="h-2" />

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{task.progress}%</span>
            </div>

            {/* ── Error message ──────────────────────────────────────── */}
            {task.error_message && (
              <p className="text-xs text-red-600">{task.error_message}</p>
            )}
          </div>
        ))}

        {/* ── Action buttons ─────────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2 pt-2">
          {showStartProcessing && (
            <Button size="sm" onClick={onStartProcessing}>
              Start Processing
            </Button>
          )}

          {showRetry && statusData.tasks.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onRetry(statusData.tasks[0].task_type)}
            >
              Retry
            </Button>
          )}

          {showGenerateEmbeddings && (
            <Button size="sm" variant="secondary" onClick={onGenerateEmbeddings}>
              Generate Embeddings
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
