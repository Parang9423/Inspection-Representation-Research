export type SplitCode = 'unassigned' | 'train' | 'valid' | 'test'
export type ReviewStatus = 'unreviewed' | 'reviewing' | 'reviewed'
export type FolderWorkStatus = 'idle' | 'working' | 'completed'

export interface FolderItem {
  folder_name: string
  image_count: number
  reviewed_count: number
  reviewing_count: number
  work_status: FolderWorkStatus
  working_by?: string | null
  working_at?: string | null
  heartbeat_at?: string | null
  last_scanned_at?: string | null
  progress: number
}

export interface ImageItem {
  image_id: string
  filename: string
  source_label: string
  label: string
  split: SplitCode
  status: string
  image_url: string
  thumbnail_url?: string
  cam_url: string
  version: number
  assigned_to?: string | null
  review_status: ReviewStatus
  reviewed_by?: string | null
  reviewed_at?: string | null
  locked_by?: string | null
  locked_at?: string | null
}

export interface HotkeyItem {
  key: string
  label: string
}

export interface WorkLog {
  log_id: number
  folder_name?: string | null
  actor?: string | null
  action: string
  detail?: string | null
  created_at: string
}

export interface ScanStatus {
  status: string
  phase?: string
  current_folder?: string | null
  discovered?: number
  processed?: number
  added?: number
  updated?: number
  unchanged?: number
  error?: string | null
  running?: boolean
}
