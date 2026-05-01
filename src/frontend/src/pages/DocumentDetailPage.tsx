import { useParams } from 'react-router-dom';

export default function DocumentDetailPage() {
  const { documentId } = useParams<{ documentId: string }>();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Document Detail</h1>
        <p className="mt-1 text-muted-foreground">
          Viewing document: <span className="font-mono">{documentId}</span>
        </p>
      </div>
    </div>
  );
}
