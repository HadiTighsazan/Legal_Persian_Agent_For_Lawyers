export interface Document {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: number | null;
  status: string;
  created_at: string;
  updated_at?: string;
  mime_type?: string;
  error_message?: string | null;
  processing_status?: string;
  chunks_count?: number;
}

export interface UploadResponse {
  id: string;
  title: string;
  original_filename: string;
  file_size: number;
  total_pages: number | null;
  status: string;
  created_at: string;
}

export interface ProcessingTask {
  task_type: string;
  status: string;
  progress: number;
  error_message: string | null;
}

export interface ProcessingStatusResponse {
  document_id: string;
  status: string;
  progress: number;
  tasks: ProcessingTask[];
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ---------------------------------------------------------------------------
// Monitoring / Chunk Visualization Types
// ---------------------------------------------------------------------------

export interface ExtractedTextResponse {
  document_id: string;
  extracted_text: string;
  extracted_text_length: number;
  total_pages: number | null;
  extraction_method: string | null;
  garbled_score: number | null;
}

export interface DocumentChunk {
  id: string;
  chunk_index: number;
  page_start: number;
  page_end: number;
  content: string;
  token_count: number | null;
  metadata: Record<string, unknown>;
}

export interface ChunksResponse {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  next: number | null;
  previous: number | null;
  results: DocumentChunk[];
}
