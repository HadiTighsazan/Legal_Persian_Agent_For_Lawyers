import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, FileText, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { listDocuments } from '@/lib/api/documents';
import type { Document } from '@/types/document';

export default function MonitoringDocumentPicker() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const resp = await listDocuments({ page_size: 100 });
        if (!cancelled) setDocuments(resp.results);
      } catch {
        // Silently fail for dev tool
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = documents.filter(
    (d) =>
      !search ||
      d.title.toLowerCase().includes(search.toLowerCase()) ||
      d.original_filename.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] p-6 gap-4">
      <div className="flex items-center gap-3">
        <Activity className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-bold">Monitoring — Document Picker</h1>
      </div>
      <p className="text-sm text-muted-foreground">
        Select a document to inspect its text extraction and chunking pipeline.
      </p>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search documents..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-auto">
        {loading && (
          <p className="text-sm text-muted-foreground italic">Loading documents...</p>
        )}
        {!loading && filtered.length === 0 && (
          <p className="text-sm text-muted-foreground italic">
            {search ? 'No documents match your search.' : 'No documents found. Upload a document first.'}
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((doc) => (
            <button
              key={doc.id}
              onClick={() => navigate(`/monitoring/${doc.id}`)}
              className="flex items-start gap-3 rounded-lg border p-4 text-left hover:border-primary hover:bg-accent/50 transition-colors cursor-pointer"
            >
              <FileText className="h-5 w-5 mt-0.5 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="font-medium truncate">{doc.title}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {doc.original_filename} — {doc.status}
                </p>
                <p className="text-xs text-muted-foreground">
                  {doc.total_pages ?? '?'} pages
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
