import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SendHorizontal, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────

interface MessageInputProps {
  onSend: (content: string) => void;
  isDisabled?: boolean;
  placeholder?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const MAX_CHARS = 10_000;
const CHAR_COUNTER_THRESHOLD = 500;

// ── Component ──────────────────────────────────────────────────────────────

export default function MessageInput({
  onSend,
  isDisabled = false,
  placeholder = 'Ask a question about this document...',
}: MessageInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea (max ~5 lines)
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const lineHeight = 20; // ~1.25rem at text-sm
    const maxHeight = lineHeight * 5 + 16; // 5 lines + padding (py-2 = 16px)
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  }, []);

  // Reset height when cleared
  useEffect(() => {
    if (!value) {
      const textarea = textareaRef.current;
      if (textarea) {
        textarea.style.height = 'auto';
      }
    }
  }, [value]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isDisabled) return;
    onSend(trimmed);
    setValue('');
    // Refocus after state update
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  }, [value, isDisabled, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const newValue = e.target.value;
      if (newValue.length <= MAX_CHARS) {
        setValue(newValue);
        adjustHeight();
      }
    },
    [adjustHeight],
  );

  const isEmpty = value.trim().length === 0;
  const showCharCounter = value.length > CHAR_COUNTER_THRESHOLD;

  return (
    <div className="flex items-end gap-2 border-t bg-background p-4">
      <div className="relative flex-1">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={isDisabled ? 'Waiting for response...' : placeholder}
          disabled={isDisabled}
          rows={1}
          className={cn(
            'min-h-[40px] resize-none py-2 pr-12 text-sm',
            'scrollbar-thin',
          )}
          aria-label="Message input"
        />
        {/* Character counter */}
        {showCharCounter && (
          <div className="absolute bottom-1 right-3 text-[10px] text-muted-foreground/60 pointer-events-none select-none">
            {value.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
          </div>
        )}
      </div>
      <Button
        onClick={handleSubmit}
        disabled={isEmpty || isDisabled}
        size="icon"
        className="shrink-0"
        aria-label={isDisabled ? 'Waiting for response' : 'Send message'}
      >
        {isDisabled ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <SendHorizontal className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}
