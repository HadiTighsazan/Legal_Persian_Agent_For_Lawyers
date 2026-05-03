import { useNavigate } from "react-router-dom";
import type { Document } from "@/types/document";
import { Card, CardContent } from "@/components/ui/card";
import StatusBadge from "@/components/documents/StatusBadge";

interface DocumentCardProps {
  document: Document;
}

/**
 * Format a file size in bytes to a human-readable string (KB, MB, GB).
 */
function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const value = bytes / Math.pow(k, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * Format an ISO 8601 date string to a readable format (e.g., "Apr 18, 2026").
 */
function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function DocumentCard({ document }: DocumentCardProps) {
  const navigate = useNavigate();

  const handleClick = () => {
    navigate(`/documents/${document.id}`);
  };

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md"
      onClick={handleClick}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-base font-semibold text-foreground">
              {document.title}
            </h3>
            <p className="mt-0.5 truncate text-sm text-muted-foreground">
              {document.original_filename}
            </p>
          </div>
          <StatusBadge status={document.status} />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">Size:</span>{" "}
            <span className="font-medium">{formatFileSize(document.file_size)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Pages:</span>{" "}
            <span className="font-medium">
              {document.total_pages !== null ? document.total_pages : "—"}
            </span>
          </div>
          <div className="col-span-2">
            <span className="text-muted-foreground">Uploaded:</span>{" "}
            <span className="font-medium">{formatDate(document.created_at)}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
