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
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Search className="h-8 w-8 text-primary" />
      </div>

      {/* Heading */}
      <h2 className="mb-2 text-xl font-semibold">تحقیق حقوقی سراسری</h2>
      <p className="mb-8 max-w-md text-sm text-muted-foreground leading-relaxed">
        از تمام پایگاه‌های حقوقی شامل قوانین مصوب، رویه‌های قضایی و نظریات مشورتی
        به طور همزمان جستجو کنید و پاسخ‌های ترکیبی دریافت نمایید.
      </p>

      {/* Hub Overview Cards */}
      <div className="mb-8 grid w-full max-w-lg grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="border-blue-200 dark:border-blue-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Scale className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">قوانین مصوب</span>
          </CardContent>
        </Card>
        <Card className="border-emerald-200 dark:border-emerald-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Gavel className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">رویه‌های قضایی</span>
          </CardContent>
        </Card>
        <Card className="border-orange-200 dark:border-orange-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <BookOpen className="h-5 w-5 text-orange-600 dark:text-orange-400" />
            <span className="text-xs font-medium text-orange-700 dark:text-orange-300">نظریات مشورتی</span>
          </CardContent>
        </Card>
      </div>

      {/* Suggested Questions */}
      <div className="w-full max-w-lg space-y-2">
        <p className="mb-3 text-xs text-muted-foreground">پرسش‌های پیشنهادی</p>
        {SUGGESTED_QUESTIONS.map((q, i) => {
          const Icon = q.icon;
          return (
            <button
              key={i}
              onClick={() => onSend(q.text)}
              className="flex w-full items-start gap-3 rounded-lg border bg-card p-3 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="leading-relaxed">{q.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
