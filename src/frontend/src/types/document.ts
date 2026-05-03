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
