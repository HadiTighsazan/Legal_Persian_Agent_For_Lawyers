import { useState, useEffect, useRef } from "react";
import { getProcessingStatus } from "@/lib/api/documents";
import type { ProcessingStatusResponse } from "@/types/document";

interface UseProcessingStatusReturn {
  statusData: ProcessingStatusResponse | null;
  isPolling: boolean;
  error: string | null;
}

/**
 * Custom hook that polls `GET /documents/{id}/processing-status/` every 3 seconds.
 *
 * Polling starts when both `documentId` and `enabled` are truthy.
 * Polling stops automatically when the overall status is `"completed"` or `"failed"`.
 * Transient errors are caught and stored in `error` state without stopping polling.
 *
 * @param documentId - The document UUID to poll (undefined = no polling)
 * @param enabled    - Whether polling is enabled
 */
export function useProcessingStatus(
  documentId: string | undefined,
  enabled: boolean,
): UseProcessingStatusReturn {
  const [statusData, setStatusData] = useState<ProcessingStatusResponse | null>(
    null,
  );
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ref to hold the interval ID for cleanup
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Don't poll if no document ID or polling is disabled
    if (!documentId || !enabled) {
      setStatusData(null);
      setIsPolling(false);
      setError(null);
      return;
    }

    let active = true; // Guard against stale closures

    const poll = async () => {
      try {
        const data = await getProcessingStatus(documentId);
        if (!active) return;

        setStatusData(data);
        setError(null);

        // Stop polling when processing reaches a terminal state
        if (data.status === "completed" || data.status === "failed") {
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          setIsPolling(false);
        }
      } catch (err: unknown) {
        if (!active) return;
        const message =
          err instanceof Error ? err.message : "Failed to fetch processing status.";
        setError(message);
        // Continue polling on transient errors — don't stop
      }
    };

    // Start polling
    setIsPolling(true);

    // Fire immediately (don't wait 3s for the first poll)
    poll();

    // Then poll every 3 seconds
    intervalRef.current = setInterval(poll, 3000);

    // Cleanup on unmount or when deps change
    return () => {
      active = false;
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      setIsPolling(false);
    };
  }, [documentId, enabled]);

  return { statusData, isPolling, error };
}
