import { Scale, MessageSquare, Lightbulb, AlertTriangle, Gavel } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

interface StrategistEmptyStateProps {
  onSend: (content: string) => void;
}

const SUGGESTED_CASES = [
  {
    text: 'I have a contract dispute with my business partner over profit sharing. We had a verbal agreement but no written contract.',
    icon: Scale,
  },
  {
    text: 'My landlord is refusing to return my security deposit without valid reason. What are my legal options?',
    icon: Gavel,
  },
  {
    text: 'I was involved in a car accident and the other party\'s insurance is not covering all damages. What should I do?',
    icon: AlertTriangle,
  },
  {
    text: 'I need to draft a prenuptial agreement. What are the key legal requirements in Iranian family law?',
    icon: Lightbulb,
  },
];

export default function StrategistEmptyState({ onSend }: StrategistEmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 text-center">
      {/* Icon */}
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <Scale className="h-8 w-8 text-primary" />
      </div>

      {/* Heading */}
      <h2 className="mb-2 text-xl font-semibold">Interactive Strategist</h2>
      <p className="mb-8 max-w-md text-sm text-muted-foreground leading-relaxed">
        Describe your legal case and get a structured strategic analysis with
        success probability, risk assessment, and actionable recommendations
        — all grounded in Iranian law and judicial precedents.
      </p>

      {/* How It Works Cards */}
      <div className="mb-8 grid w-full max-w-lg grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="border-blue-200 dark:border-blue-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <MessageSquare className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">Describe Your Case</span>
          </CardContent>
        </Card>
        <Card className="border-emerald-200 dark:border-emerald-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Scale className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
            <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">Get Strategic Analysis</span>
          </CardContent>
        </Card>
        <Card className="border-orange-200 dark:border-orange-800">
          <CardContent className="flex flex-col items-center gap-1.5 p-4">
            <Lightbulb className="h-5 w-5 text-orange-600 dark:text-orange-400" />
            <span className="text-xs font-medium text-orange-700 dark:text-orange-300">Receive Recommendations</span>
          </CardContent>
        </Card>
      </div>

      {/* Suggested Cases */}
      <div className="w-full max-w-lg space-y-2">
        <p className="mb-3 text-xs text-muted-foreground">Try describing one of these cases</p>
        {SUGGESTED_CASES.map((q, i) => {
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
