import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
}

interface StatusConfig {
  label: string;
  className: string;
}

const STATUS_MAP: Record<string, StatusConfig> = {
  uploaded: {
    label: "Uploaded",
    className: "bg-gray-100 text-gray-800",
  },
  pending: {
    label: "Pending",
    className: "bg-gray-100 text-gray-800",
  },
  running: {
    label: "Running",
    className: "bg-blue-100 text-blue-800 animate-pulse",
  },
  processing: {
    label: "Processing",
    className: "bg-blue-100 text-blue-800 animate-pulse",
  },
  completed: {
    label: "Completed",
    className: "bg-green-100 text-green-800",
  },
  failed: {
    label: "Failed",
    className: "bg-red-100 text-red-800",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-yellow-100 text-yellow-800",
  },
};

const FALLBACK: StatusConfig = {
  label: "Unknown",
  className: "bg-gray-100 text-gray-800",
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? FALLBACK;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        config.className,
      )}
    >
      {config.label}
    </span>
  );
}
