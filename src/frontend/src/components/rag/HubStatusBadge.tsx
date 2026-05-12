import { cn } from '@/lib/utils';
import { FileText, Scale, Gavel, BookOpen, type LucideIcon } from 'lucide-react';

interface HubStatusBadgeProps {
  hubType: string;
  className?: string;
}

interface HubConfig {
  label: string;
  icon: LucideIcon;
  className: string;
}

const HUB_CONFIG: Record<string, HubConfig> = {
  legislation: {
    label: 'قوانین مصوب',
    icon: Scale,
    className:
      'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300 border-blue-200 dark:border-blue-800',
  },
  judicial_precedent: {
    label: 'رویه‌های قضایی',
    icon: Gavel,
    className:
      'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
  },
  advisory_opinion: {
    label: 'نظریات مشورتی',
    icon: BookOpen,
    className:
      'bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-300 border-orange-200 dark:border-orange-800',
  },
};

const FALLBACK_CONFIG: HubConfig = {
  label: 'منبع حقوقی',
  icon: FileText,
  className:
    'bg-gray-50 text-gray-700 dark:bg-gray-950/30 dark:text-gray-300 border-gray-200 dark:border-gray-800',
};

export default function HubStatusBadge({ hubType, className }: HubStatusBadgeProps) {
  const config = HUB_CONFIG[hubType] ?? FALLBACK_CONFIG;
  const Icon = config.icon;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        config.className,
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
}
