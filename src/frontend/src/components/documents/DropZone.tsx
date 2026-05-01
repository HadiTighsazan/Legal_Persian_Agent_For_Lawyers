import { useState, useRef, useCallback } from "react";
import { Upload, FileText } from "lucide-react";
import { cn } from "@/lib/utils";

interface DropZoneProps {
  onFileSelect: (file: File) => void;
  onError: (error: string) => void;
  disabled?: boolean;
  accept?: string;
  maxSize?: number;
}

export default function DropZone({
  onFileSelect,
  onError,
  disabled = false,
  accept = ".pdf",
  maxSize = 500 * 1024 * 1024, // 500MB
}: DropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback(
    (file: File): boolean => {
      // Check file type: must be PDF
      if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
        onError("Only PDF files are allowed.");
        return false;
      }

      // Check file size
      if (file.size > maxSize) {
        onError("File size must be under 500MB.");
        return false;
      }

      return true;
    },
    [maxSize, onError]
  );

  const handleFile = useCallback(
    (file: File) => {
      if (validateFile(file)) {
        setSelectedFile(file);
        onFileSelect(file);
      }
    },
    [validateFile, onFileSelect]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) {
      setIsDragOver(true);
    }
  }, [disabled]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      if (disabled) return;

      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFile(files[0]);
      }
    },
    [disabled, handleFile]
  );

  const handleClick = useCallback(() => {
    if (!disabled && inputRef.current) {
      inputRef.current.click();
    }
  }, [disabled]);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleFile(files[0]);
      }
      // Reset input so the same file can be re-selected
      e.target.value = "";
    },
    [handleFile]
  );

  return (
    <div
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={cn(
        "relative flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-12 transition-colors",
        isDragOver
          ? "border-primary bg-accent/50"
          : "border-muted-foreground/25 hover:border-muted-foreground/50",
        disabled && "cursor-not-allowed opacity-50"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={handleInputChange}
        disabled={disabled}
      />

      {selectedFile ? (
        <>
          <FileText className="mb-4 h-12 w-12 text-primary" />
          <p className="text-sm font-medium">{selectedFile.name}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Click or drag to replace
          </p>
        </>
      ) : (
        <>
          <Upload className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-sm font-medium">
            Drag & drop your PDF here, or click to browse
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Only PDF files up to 500MB are supported
          </p>
        </>
      )}
    </div>
  );
}
