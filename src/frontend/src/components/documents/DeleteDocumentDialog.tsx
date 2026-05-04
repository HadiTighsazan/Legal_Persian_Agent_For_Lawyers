import { useState } from "react";
import { Loader2 } from "lucide-react";
import { deleteDocument } from "@/lib/api/documents";
import { toast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface DeleteDocumentDialogProps {
  documentId: string;
  documentTitle: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}

export default function DeleteDocumentDialog({
  documentId,
  documentTitle,
  open,
  onOpenChange,
  onDeleted,
}: DeleteDocumentDialogProps) {
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteDocument(documentId);
      onOpenChange(false);
      onDeleted();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to delete document.";
      toast({ variant: "destructive", title: "Error", description: message });
      onOpenChange(false);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        onInteractOutside={(e: Event) => {
          if (isDeleting) e.preventDefault();
        }}
        onEscapeKeyDown={(e: KeyboardEvent) => {
          if (isDeleting) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>Delete Document</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete <strong>{documentTitle}</strong>?
            This will permanently remove all chunks, embeddings, and
            conversation history.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={isDeleting}
          >
            {isDeleting && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
