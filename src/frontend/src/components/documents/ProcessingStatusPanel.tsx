import type { ProcessingStatusResponse } from "@/types/document";
import StatusBadge from "@/components/documents/StatusBadge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, CheckCircle2, Clock, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

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
 * Human-readable descriptions for each task type's processing stage.
 */
const TASK_STATUS_DESCRIPTIONS: Record<string, Record<string, string>> = {
  extract: {
    pending: "Waiting to start text extraction...",
    running: "Extracting text from document pages...",
    processing: "Extracting text from document pages...",
    completed: "Text extraction complete",
    failed: "Text extraction failed",
  },
  chunk: {
    pending: "Waiting to start chunking...",
    running: "Splitting text into semantic chunks...",
    processing: "Splitting text into semantic chunks...",
    completed: "Chunking complete",
    failed: "Chunking failed",
  },
  embed: {
    pending: "Waiting to generate embeddings...",
    running: "Generating vector embeddings...",
    processing: "Generating vector embeddings...",
    completed: "Embeddings generated",
    failed: "Embedding generation failed",
  },
};

const DEFAULT_STATUS_DESCRIPTION = "Processing...";

function getTaskDescription(taskType: string, status: string): string {
  const typeDescriptions = TASK_STATUS_DESCRIPTIONS[taskType];
  if (!typeDescriptions) return DEFAULT_STATUS_DESCRIPTION;
  return typeDescriptions[status] ?? DEFAULT_STATUS_DESCRIPTION;
}

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
      <Card className="border-border/60">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">Processing Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-sm text-muted-foreground/70">
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
  const showStartProcessing =
    documentStatus === "uploaded" &&
    processingStatus !== "processing" &&
    processingStatus !== "completed";
  const showRetry = processingStatus === "failed";
  const showGenerateEmbeddings =
    processingStatus === "completed" && statusData.tasks.length > 0;

  return (
    <Card className="border-border/60">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold">Processing Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* ── Per-task rows ──────────────────────────────────────────── */}
        {statusData.tasks.map((task) => {
          const isActive = task.status === "running" || task.status === "processing";
          const isComplete = task.status === "completed";
          const isFailed = task.status === "failed";
          const isPending = task.status === "pending";

          return (
            <div key={task.task_type} className="space-y-2">
              {/* Header row */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {/* Status icon */}
                  {isComplete ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  ) : isActive ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  ) : isFailed ? (
                    <AlertCircle className="h-4 w-4 text-destructive" />
                  ) : (
                    <Clock className="h-4 w-4 text-muted-foreground/50" />
                  )}
                  <span className="text-sm font-medium">
                    {TASK_TYPE_LABELS[task.task_type] ?? DEFAULT_TASK_LABEL}
                  </span>
                </div>
                <StatusBadge status={task.status} />
              </div>

              {/* Progress bar */}
              <div className="relative">
                <Progress
                  value={task.progress}
                  className={cn(
                    "h-2 transition-all duration-500",
                    isActive && task.progress === 0 && "animate-pulse",
                  )}
                />
              </div>

              {/* Progress percentage + description */}
              <div className="flex items-center justify-between text-xs text-muted-foreground/70">
                <span className="flex items-center gap-1.5">
                  {isActive && (
                    <span className="inline-flex items-center gap-1">
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                    </span>
                  )}
                  {getTaskDescription(task.task_type, task.status)}
                </span>
                <span className="font-medium tabular-nums">
                  {isComplete ? "100%" : isPending ? "—" : `${task.progress}%`}
                </span>
              </div>

              {/* ── Error message ────────────────────────────────────── */}
              {task.error_message && (
                <div className="flex items-start gap-1.5 rounded-lg bg-destructive/8 p-2.5">
                  <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                  <p className="text-xs text-destructive/90 leading-relaxed">{task.error_message}</p>
                </div>
              )}
            </div>
          );
        })}

        {/* ── Action buttons ─────────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2 pt-1">
          {showStartProcessing && (
            <Button size="sm" onClick={onStartProcessing} className="rounded-lg">
              Start Processing
            </Button>
          )}

          {showRetry && statusData.tasks.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => onRetry(statusData.tasks[0].task_type)}
              className="rounded-lg border-border/60"
            >
              Retry
            </Button>
          )}

          {showGenerateEmbeddings && (
            <Button size="sm" variant="secondary" onClick={onGenerateEmbeddings} className="rounded-lg">
              Generate Embeddings
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
