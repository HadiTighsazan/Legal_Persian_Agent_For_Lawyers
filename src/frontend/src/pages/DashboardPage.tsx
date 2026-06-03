import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/authStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Search, Scale, ArrowRight } from 'lucide-react';

export default function DashboardPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const displayName = user?.full_name || user?.email || 'User';

  return (
    <div className="space-y-8">
      {/* Welcome heading */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Welcome back, {displayName}
        </h1>
        <p className="mt-1 text-muted-foreground">
          Here's an overview of your account.
        </p>
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">Quick Actions</h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Legal Research Card */}
          <Card
            className="cursor-pointer transition-colors hover:bg-accent/50"
            onClick={() => navigate('/legal-research')}
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Legal Research
                </CardTitle>
                <Search className="h-5 w-5 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-3">
                Search across all legal hubs — legislation, judicial precedents,
                and advisory opinions — simultaneously.
              </p>
              <Button variant="outline" size="sm" className="gap-2">
                Start Research
                <ArrowRight className="h-4 w-4" />
              </Button>
            </CardContent>
          </Card>

          {/* Interactive Strategist Card */}
          <Card
            className="cursor-pointer transition-colors hover:bg-accent/50"
            onClick={() => navigate('/strategist')}
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Interactive Strategist
                </CardTitle>
                <Scale className="h-5 w-5 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-3">
                Describe your case and get a strategic analysis with success
                probability, risk assessment, and recommendations.
              </p>
              <Button variant="outline" size="sm" className="gap-2">
                Start Analysis
                <ArrowRight className="h-4 w-4" />
              </Button>
            </CardContent>
          </Card>

          {/* Document Chat Card */}
          <Card
            className="cursor-pointer transition-colors hover:bg-accent/50"
            onClick={() => navigate('/documents')}
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Document Chat
                </CardTitle>
                <Search className="h-5 w-5 text-primary" />
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-3">
                Select a document and ask questions about its content using
                local RAG.
              </p>
              <Button variant="outline" size="sm" className="gap-2">
                Browse Documents
                <ArrowRight className="h-4 w-4" />
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Stat cards */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">Overview</h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Documents
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">&mdash;</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Active Conversations
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">&mdash;</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Storage Used
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">&mdash;</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
