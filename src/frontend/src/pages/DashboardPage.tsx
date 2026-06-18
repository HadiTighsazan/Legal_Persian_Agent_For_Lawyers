import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Search, Scale, FileText, ArrowRight } from 'lucide-react';

export default function DashboardPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const displayName = user?.full_name || user?.email || 'User';

  return (
    <div className="space-y-8">
      {/* Welcome heading */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Welcome back, {displayName}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground/70">
          Here's an overview of your account.
        </p>
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="mb-4 text-sm font-semibold text-muted-foreground/60 uppercase tracking-wider">
          Quick Actions
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Legal Research Card */}
          <Card
            className="cursor-pointer transition-all duration-200 hover:shadow-md hover:border-primary/20 border-border/60"
            onClick={() => navigate('/legal-research')}
          >
            <CardHeader className="pb-2 flex-row items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Legal Research
              </CardTitle>
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/8">
                <Search className="h-4 w-4 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground/70 leading-relaxed mb-3">
                Search across all legal hubs — legislation, judicial precedents,
                and advisory opinions — simultaneously.
              </p>
              <Button variant="outline" size="sm" className="gap-2 rounded-lg border-border/60">
                Start Research
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </CardContent>
          </Card>

          {/* Interactive Strategist Card */}
          <Card
            className="cursor-pointer transition-all duration-200 hover:shadow-md hover:border-primary/20 border-border/60"
            onClick={() => navigate('/strategist')}
          >
            <CardHeader className="pb-2 flex-row items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Interactive Strategist
              </CardTitle>
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/8">
                <Scale className="h-4 w-4 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground/70 leading-relaxed mb-3">
                Describe your case and get a strategic analysis with success
                probability, risk assessment, and recommendations.
              </p>
              <Button variant="outline" size="sm" className="gap-2 rounded-lg border-border/60">
                Start Analysis
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </CardContent>
          </Card>

          {/* Document Chat Card */}
          <Card
            className="cursor-pointer transition-all duration-200 hover:shadow-md hover:border-primary/20 border-border/60"
            onClick={() => navigate('/documents')}
          >
            <CardHeader className="pb-2 flex-row items-center justify-between">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Document Chat
              </CardTitle>
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/8">
                <FileText className="h-4 w-4 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground/70 leading-relaxed mb-3">
                Select a document and ask questions about its content using
                local RAG.
              </p>
              <Button variant="outline" size="sm" className="gap-2 rounded-lg border-border/60">
                Browse Documents
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Stat cards */}
      <div>
        <h2 className="mb-4 text-sm font-semibold text-muted-foreground/60 uppercase tracking-wider">
          Overview
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground/70 uppercase tracking-wider">
                Total Documents
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">&mdash;</p>
            </CardContent>
          </Card>

          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground/70 uppercase tracking-wider">
                Active Conversations
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">&mdash;</p>
            </CardContent>
          </Card>

          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground/70 uppercase tracking-wider">
                Storage Used
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">&mdash;</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
