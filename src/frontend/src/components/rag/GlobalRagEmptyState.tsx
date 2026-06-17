import { Search, Scale, Gavel, BookOpen, Sparkles } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

interface GlobalRagEmptyStateProps {
  onSend: (content: string) => void;
}

const SUGGESTED_QUESTIONS = [
  {
    text: 'آخرین آرای وحدت رویه دیوان عالی کشور در چه موضوعاتی صادر شده است؟',
    icon: Gavel,
  },
  {
    text: 'شرایط و ضوابط تنظیم قراردادهای مشارکت مدنی چیست؟',
    icon: Scale,
  },
  {
    text: 'نظریات مشورتی اخیر اداره کل حقوقی درباره قراردادهای پیمانکاری',
    icon: BookOpen,
  },
  {
    text: 'خلاصه‌ای از مهمترین قوانین مصوب سال ۱۴۰۳ در حوزه حقوق تجارت',
    icon: Sparkles,
  },
];

export default function GlobalRagEmptyState({ onSend }: GlobalRagEmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 text-center">
      {/* Icon */}
      <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/8">
        <Search className="h-7 w-7 text-primary" />
      </div>

      {/* Heading */}
      <h2 className="mb-2 text-lg font-semibold">تحقیق حقوقی سراسری</h2>
      <p className="mb-8 max-w-md text-sm text-muted-foreground/70 leading-relaxed">
        از تمام پایگاه‌های حقوقی شامل قوانین مصوب، رویه‌های قضایی و نظریات مشورتی
        به طور همزمان جستجو کنید و پاسخ‌های ترکیبی دریافت نمایید.
      </p>

      {/* Hub Overview Cards */}
      <div className="mb-8 grid w-full max-w-lg grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="border-blue-200/60 dark:border-blue-800/40 shadow-none">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Scale className="h-5 w-5 text-blue-600/80 dark:text-blue-400/80" />
            <span className="text-xs font-medium text-blue-700/80 dark:text-blue-300/80">قوانین مصوب</span>
          </CardContent>
        </Card>
        <Card className="border-emerald-200/60 dark:border-emerald-800/40 shadow-none">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Gavel className="h-5 w-5 text-emerald-600/80 dark:text-emerald-400/80" />
            <span className="text-xs font-medium text-emerald-700/80 dark:text-emerald-300/80">رویه‌های قضایی</span>
          </CardContent>
        </Card>
        <Card className="border-orange-200/60 dark:border-orange-800/40 shadow-none">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <BookOpen className="h-5 w-5 text-orange-600/80 dark:text-orange-400/80" />
            <span className="text-xs font-medium text-orange-700/80 dark:text-orange-300/80">نظریات مشورتی</span>
          </CardContent>
        </Card>
      </div>

      {/* Suggested Questions */}
      <div className="w-full max-w-lg space-y-2">
        <p className="mb-3 text-xs text-muted-foreground/50">پرسش‌های پیشنهادی</p>
        {SUGGESTED_QUESTIONS.map((q, i) => {
          const Icon = q.icon;
          return (
            <button
              key={i}
              onClick={() => onSend(q.text)}
              className="flex w-full items-start gap-3 rounded-xl border border-border/60 bg-card p-3.5 text-left text-sm transition-all duration-200 hover:border-primary/20 hover:bg-accent/50 hover:shadow-sm"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground/60" />
              <span className="leading-relaxed">{q.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
