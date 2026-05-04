import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import DropZone from "@/components/documents/DropZone";
import { uploadDocument, triggerProcessing } from "@/lib/api/documents";
import { useToast } from "@/hooks/use-toast";

export default function UploadPage() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = (selectedFile: File) => {
    setFile(selectedFile);
    setError(null);
  };

  const handleError = (errorMessage: string) => {
    setError(errorMessage);
    setFile(null);
  };

  const handleUpload = () => {
    if (!file || !title.trim() || uploading) return;

    setUploading(true);
    setProgress(0);
    setError(null);

    uploadDocument(file, title.trim(), {
      onProgress: (percentage: number) => {
        setProgress(percentage);
      },
      onSuccess: async (response) => {
        setUploading(false);
        toast({
          title: "Document uploaded!",
          description: "Starting processing...",
        });

        // Auto-trigger the document processing pipeline (text extraction + chunking).
        // This eliminates the need for the user to manually click "Start Processing"
        // on the document detail page.
        try {
          await triggerProcessing(response.id);
        } catch {
          // Processing trigger failure is non-fatal — the user can still manually
          // trigger it from the document detail page.
          toast({
            variant: "destructive",
            title: "Processing trigger failed",
            description: "You can start processing manually from the document page.",
          });
        }

        navigate(`/documents/${response.id}`);
      },
      onError: (error) => {
        setUploading(false);
        setProgress(0);

        if (error.status === 401) {
          toast({
            variant: "destructive",
            title: "Session expired",
            description: "Please log in again.",
          });
          navigate("/login");
        } else if (error.status === 403) {
          toast({
            variant: "destructive",
            title: "Access denied",
          });
        } else if (error.status >= 400 && error.status < 500) {
          // 4xx — show field error in the form
          setError(error.message);
        } else if (error.status >= 500) {
          toast({
            variant: "destructive",
            title: "Server error",
            description: "Please try again.",
          });
        } else if (error.status === 0) {
          // Network error or timeout
          toast({
            variant: "destructive",
            title: "Network error",
            description: "Check your connection.",
          });
        }
      },
    });
  };

  const isSubmitDisabled = !file || !title.trim() || uploading;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Document</h1>
        <p className="mt-1 text-muted-foreground">
          Upload a new document to your knowledge base.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Document Details</CardTitle>
          <CardDescription>
            Provide a title and select a PDF file to upload.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Title input */}
          <div className="space-y-2">
            <Label htmlFor="title">Document Title</Label>
            <Input
              id="title"
              placeholder="Enter a descriptive title for your document"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={uploading}
            />
          </div>

          {/* Drop zone */}
          <div className="space-y-2">
            <Label>File</Label>
            <DropZone
              onFileSelect={handleFileSelect}
              onError={handleError}
              disabled={uploading}
            />
          </div>

          {/* Error display */}
          {error && (
            <div className="text-sm text-destructive">{error}</div>
          )}

          {/* Progress bar */}
          {uploading && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Uploading...</span>
                <span className="font-medium">{progress}%</span>
              </div>
              <Progress value={progress} />
            </div>
          )}

          {/* Submit button */}
          <Button
            onClick={handleUpload}
            disabled={isSubmitDisabled}
            className="w-full"
          >
            {uploading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading...
              </>
            ) : (
              "Upload"
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
