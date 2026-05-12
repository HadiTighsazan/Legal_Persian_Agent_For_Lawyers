import { cn } from '@/lib/utils';
import { useConversationStore } from '@/stores/conversationStore';
import type { RagMode } from '@/api/conversations';

interface ModeOption {
  value: RagMode;
  label: string;
  description: string;
}

const MODE_OPTIONS: ModeOption[] = [
  {
    value: 'local_rag',
    label: 'سند جاری',
    description: 'پرسش از سند انتخاب‌شده',
  },
  {
    value: 'global_rag',
    label: 'تحقیق سراسری',
    description: 'جستجو در تمام پایگاه‌های حقوقی',
  },
];

export default function ModeSelector() {
  const ragMode = useConversationStore((s) => s.ragMode);
  const setRagMode = useConversationStore((s) => s.setRagMode);

  return (
    <div className="flex items-center gap-1 rounded-lg border bg-muted/50 p-1" role="radiogroup" aria-label="حالت جستجو">
      {MODE_OPTIONS.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={ragMode === option.value}
          onClick={() => setRagMode(option.value)}
          className={cn(
            'flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-all',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
            ragMode === option.value
              ? 'bg-background text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
          title={option.description}
        >
          <span className="block leading-tight">{option.label}</span>
          <span className="block text-[10px] font-normal text-muted-foreground/70">
            {option.description}
          </span>
        </button>
      ))}
    </div>
  );
}
