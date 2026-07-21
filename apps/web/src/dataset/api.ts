import axios from 'axios'
import type { HotkeyItem, ImageItem, ScanStatus, WorkLog } from './types'

const api = axios.create({ baseURL: '/api' })

export async function fetchFolders() {
  return (await api.get('/folder-work/folders')).data
}

export async function fetchFolderImages(params: Record<string, unknown>) {
  return (await api.get<{ items: ImageItem[]; total: number }>('/collaboration/folder-images', { params })).data
}

export async function fetchHotkeys() {
  return (await api.get<{ items: HotkeyItem[] }>('/labels/hotkeys')).data
}

export async function fetchHistory(imageId: string) {
  return (await api.get<{ items: Array<Record<string, unknown>> }>(`/collaboration/images/${imageId}/history`)).data
}

export async function fetchWorkLogs(folder?: string) {
  return (await api.get<{ items: WorkLog[] }>('/folder-work/logs', {
    params: { folder_name: folder, limit: 100 },
  })).data
}

export async function fetchScanStatus() {
  return (await api.get<ScanStatus>('/scan/status')).data
}

export async function scanDataset(mode: 'quick' | 'full') {
  return (await api.post(`/scan/${mode}`)).data
}

export async function startFolder(folder: string, actor: string) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/start`, { actor })).data
}

export async function releaseFolder(folder: string, actor: string, force = false) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/release`, { actor, force })).data
}

export async function completeFolder(folder: string, actor: string) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/complete`, { actor })).data
}

export async function folderHeartbeat(folder: string, actor: string) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/heartbeat`, { actor })).data
}

export async function acquireLock(imageId: string, actor: string) {
  return (await api.post<ImageItem>(`/collaboration/images/${imageId}/lock`, { actor })).data
}

export async function releaseLock(imageId: string, actor: string) {
  return (await api.post(`/collaboration/images/${imageId}/unlock`, { actor })).data
}

export async function imageHeartbeat(imageId: string, actor: string) {
  return (await api.post(`/collaboration/images/${imageId}/heartbeat`, { actor })).data
}

export async function updateImage(payload: { image_id: string; actor: string; expected_version: number; label: string }) {
  return (await api.patch<ImageItem>('/collaboration/images/update', payload)).data
}

export async function backupDelete(payload: { image_id: string; actor: string; expected_version: number }) {
  return (await api.post<{ moved: number }>('/collaboration/images/backup-delete', payload)).data
}
