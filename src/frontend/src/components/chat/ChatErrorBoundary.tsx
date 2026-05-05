import { Component } from 'react';
import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

// ── Props ────────────────────────────────────────────────────────────────────

interface ChatErrorBoundaryProps {
  children: React.ReactNode;
}

// ── State ────────────────────────────────────────────────────────────────────

interface ChatErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

// ── Component ────────────────────────────────────────────────────────────────

export default class ChatErrorBoundary extends Component<
  ChatErrorBoundaryProps,
  ChatErrorBoundaryState
> {
  constructor(props: ChatErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ChatErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error('[ChatErrorBoundary] Unhandled error in chat component tree:', error, errorInfo);
  }

  handleReload = (): void => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
          <AlertCircle className="h-12 w-12 text-destructive mb-4" />
          <h2 className="text-xl font-semibold tracking-tight">
            Something went wrong
          </h2>
          <p className="mt-1 text-sm text-muted-foreground max-w-sm">
            An unexpected error occurred in the chat. Please try reloading.
          </p>
          <Button
            variant="default"
            className="mt-6"
            onClick={this.handleReload}
          >
            Reload
          </Button>
        </div>
      );
    }

    return this.props.children;
  }
}
