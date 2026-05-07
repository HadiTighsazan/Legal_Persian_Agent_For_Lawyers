import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { getDocument, getDocumentChunks, getExtractedText } from '@/lib/api/documents';
import type { Document, DocumentChunk, ExtractedTextResponse } from '@/types/document';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExtractionMeta {
  method: string | null;
  garbledScore: number | null;
  textLength: number;
  totalPages: number | null;
  chunkCount: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMethod(method: string | null): string {
  switch (method) {
    case 'pymupdf':
      return 'PyMuPDF';
    case 'pdfplumber':
      return 'pdfplumber';
    case 'tesseract':
      return 'Tesseract OCR';
    default:
      return method ?? 'N/A';
  }
}

function formatGarbledScore(score: number | null): string {
  if (score === null || score === undefined) return 'N/A';
  return score.toFixed(3);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MonitoringHeader({
  document: doc,
  meta,
  onBack,
}: {
  document: Document | null;
  meta: ExtractionMeta | null;
  onBack: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 border-b pb-3">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack} aria-label="Back to documents">
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <h1 className="text-xl font-bold truncate" dir="rtl">
          Monitoring: {doc?.title ?? 'Loading...'}
        </h1>
      </div>
      {meta && (
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground px-1">
          <span>
            <strong>Method:</strong> {formatMethod(meta.method)}
          </span>
          <span>
            <strong>Garbled Score:</strong> {formatGarbledScore(meta.garbledScore)}
          </span>
          <span>
            <strong>Chunks:</strong> {meta.chunkCount}
          </span>
          <span>
            <strong>Pages:</strong> {meta.totalPages ?? 'N/A'}
          </span>
          <span>
            <strong>Text Length:</strong> {meta.textLength.toLocaleString()} chars
          </span>
        </div>
      )}
    </div>
  );
}

function RawTextPanel({ text }: { text: string }) {
  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">Raw Extracted Text</h3>
      <div className="flex-1 overflow-auto rounded border bg-card p-3">
        <pre className="text-xs leading-relaxed whitespace-pre-wrap font-mono" dir="rtl">
          {text || <span className="text-muted-foreground italic">No extracted text available.</span>}
        </pre>
      </div>
    </div>
  );
}

// Color palette for chunk backgrounds (10 distinct colors, cycling)
const CHUNK_COLORS = [
  { bg: 'bg-blue-50/40', border: 'border-blue-300', label: 'bg-blue-500', labelText: 'text-white' },
  { bg: 'bg-emerald-50/40', border: 'border-emerald-300', label: 'bg-emerald-500', labelText: 'text-white' },
  { bg: 'bg-violet-50/40', border: 'border-violet-300', label: 'bg-violet-500', labelText: 'text-white' },
  { bg: 'bg-amber-50/40', border: 'border-amber-300', label: 'bg-amber-500', labelText: 'text-white' },
  { bg: 'bg-rose-50/40', border: 'border-rose-300', label: 'bg-rose-500', labelText: 'text-white' },
  { bg: 'bg-cyan-50/40', border: 'border-cyan-300', label: 'bg-cyan-500', labelText: 'text-white' },
  { bg: 'bg-orange-50/40', border: 'border-orange-300', label: 'bg-orange-500', labelText: 'text-white' },
  { bg: 'bg-teal-50/40', border: 'border-teal-300', label: 'bg-teal-500', labelText: 'text-white' },
  { bg: 'bg-pink-50/40', border: 'border-pink-300', label: 'bg-pink-500', labelText: 'text-white' },
  { bg: 'bg-indigo-50/40', border: 'border-indigo-300', label: 'bg-indigo-500', labelText: 'text-white' },
];

function ChunkVisualizationPanel({
  text,
  chunks,
  selectedChunk,
  onChunkClick,
}: {
  text: string;
  chunks: DocumentChunk[];
  selectedChunk: number | null;
  onChunkClick: (index: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Scroll selected chunk into view
  useEffect(() => {
    if (selectedChunk !== null && containerRef.current) {
      const el = containerRef.current.querySelector(`[data-chunk-index="${selectedChunk}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [selectedChunk]);

  if (!text || chunks.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <h3 className="text-sm font-semibold text-muted-foreground mb-2">Chunk Visualization</h3>
        <div className="flex-1 flex items-center justify-center rounded border bg-card text-sm text-muted-foreground italic">
          No chunks available to visualize.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">Chunk Visualization</h3>
      <div ref={containerRef} className="flex-1 overflow-auto rounded border bg-card p-2 space-y-3">
        {chunks.map((chunk, idx) => {
          const color = CHUNK_COLORS[idx % CHUNK_COLORS.length];
          const isSelected = selectedChunk === chunk.chunk_index;

          return (
            <div
              key={chunk.id}
              data-chunk-index={chunk.chunk_index}
              onClick={() => onChunkClick(chunk.chunk_index)}
              className={`
                rounded-md border-2 transition-all cursor-pointer
                ${color.bg} ${color.border}
                ${isSelected ? 'ring-2 ring-primary ring-offset-1 shadow-md' : 'hover:shadow-sm'}
              `}
              dir="rtl"
            >
              {/* Chunk header bar */}
              <div className={`flex items-center gap-2 px-3 py-1.5 ${color.label} text-xs font-bold ${color.labelText} rounded-t-md`}>
                <span>Chunk #{chunk.chunk_index}</span>
                <span className="opacity-80">·</span>
                <span className="opacity-80">Pages {chunk.page_start}–{chunk.page_end}</span>
                <span className="opacity-80">·</span>
                <span className="opacity-80">{chunk.token_count ?? '?'} tokens</span>
              </div>

              {/* Chunk content */}
              <div className="px-3 py-2">
                <pre className="text-xs leading-relaxed whitespace-pre-wrap font-mono">
                  {chunk.content}
                </pre>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChunkDetailsPanel({
  chunks,
  selectedChunk,
  searchFilter,
  onSearchChange,
  onChunkClick,
}: {
  chunks: DocumentChunk[];
  selectedChunk: number | null;
  searchFilter: string;
  onSearchChange: (value: string) => void;
  onChunkClick: (index: number) => void;
}) {
  const filteredChunks = useMemo(() => {
    if (!searchFilter.trim()) return chunks;
    const lower = searchFilter.toLowerCase();
    return chunks.filter(
      (c) =>
        c.content.toLowerCase().includes(lower) ||
        String(c.chunk_index).includes(lower),
    );
  }, [chunks, searchFilter]);

  return (
    <div className="flex flex-col h-full">
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">Chunk Details</h3>

      {/* Search filter */}
      <div className="relative mb-2">
        <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Filter chunks..."
          value={searchFilter}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-8 h-8 text-xs"
        />
      </div>

      {/* Chunk list */}
      <div className="flex-1 overflow-auto space-y-2">
        {filteredChunks.length === 0 && (
          <p className="text-xs text-muted-foreground italic text-center pt-4">
            {searchFilter ? 'No chunks match filter.' : 'No chunks available.'}
          </p>
        )}
        {filteredChunks.map((chunk) => {
          const isSelected = selectedChunk === chunk.chunk_index;
          const legalType = chunk.metadata?.legal_type as string | undefined;
          return (
            <button
              key={chunk.id}
              onClick={() => onChunkClick(chunk.chunk_index)}
              className={`w-full text-left rounded border p-2 transition-colors cursor-pointer ${
                isSelected
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:border-primary/50'
              }`}
            >
              {/* Chunk header */}
              <div className="flex items-center justify-between gap-2 text-xs font-medium">
                <span className="text-foreground">Chunk #{chunk.chunk_index}</span>
                <span className="text-muted-foreground">
                  Pages {chunk.page_start}–{chunk.page_end}
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                <span>Tokens: {chunk.token_count ?? 'N/A'}</span>
                {legalType && <span>Type: {legalType}</span>}
              </div>
              <Separator className="my-1" />
              {/* Chunk content preview */}
              <p
                className="text-xs leading-relaxed line-clamp-3"
                dir="rtl"
              >
                {chunk.content}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main MonitoringPage Component
// ---------------------------------------------------------------------------

export default function MonitoringPage() {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();

  const [document, setDocument] = useState<Document | null>(null);
  const [extractedText, setExtractedText] = useState<string>('');
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [extractionMeta, setExtractionMeta] = useState<ExtractionMeta | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<number | null>(null);
  const [searchFilter, setSearchFilter] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!documentId) return;

    let cancelled = false;

    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [doc, extracted, chunksResp] = await Promise.all([
          getDocument(documentId!),
          getExtractedText(documentId!),
          getDocumentChunks(documentId!),
        ]);

        if (cancelled) return;

        setDocument(doc);
        setExtractedText(extracted.extracted_text);
        setChunks(chunksResp.results);
        setExtractionMeta({
          method: extracted.extraction_method,
          garbledScore: extracted.garbled_score,
          textLength: extracted.extracted_text_length,
          totalPages: extracted.total_pages,
          chunkCount: chunksResp.count,
        });
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to load monitoring data';
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadData();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const handleBack = () => {
    navigate('/documents');
  };

  // ── Loading state ──────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <p className="text-muted-foreground">Loading monitoring data...</p>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[calc(100vh-8rem)] gap-4">
        <p className="text-destructive font-medium">Error: {error}</p>
        <Button variant="outline" onClick={handleBack}>
          Back to Documents
        </Button>
      </div>
    );
  }

  // ── Main three-panel layout ────────────────────────────────────────
  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] p-4 gap-3">
      {/* Header */}
      <MonitoringHeader
        document={document}
        meta={extractionMeta}
        onBack={handleBack}
      />

      {/* Three-panel layout */}
      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* Panel 1: Raw Text (left) */}
        <div className="flex-1 min-w-0">
          <RawTextPanel text={extractedText} />
        </div>

        {/* Panel 2: Chunk Visualization (center) */}
        <div className="flex-1 min-w-0">
          <ChunkVisualizationPanel
            text={extractedText}
            chunks={chunks}
            selectedChunk={selectedChunk}
            onChunkClick={setSelectedChunk}
          />
        </div>

        {/* Panel 3: Chunk Details (right) */}
        <div className="w-80 min-w-0">
          <ChunkDetailsPanel
            chunks={chunks}
            selectedChunk={selectedChunk}
            searchFilter={searchFilter}
            onSearchChange={setSearchFilter}
            onChunkClick={setSelectedChunk}
          />
        </div>
      </div>
    </div>
  );
}
