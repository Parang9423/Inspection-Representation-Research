import { useEffect, useMemo, useRef, useState } from 'react'
import type { InputRef } from 'antd'
import { message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import DatasetDashboard from './dataset/DatasetDashboard'
import FolderReviewView from './dataset/FolderReviewView'
import WorkLogModal from './dataset/WorkLogModal'
import {
  acquireLock, backupDelete, completeFolder, fetchFolderImages, fetchFolders,
  fetchHistory, fetchHotkeys, fetchScanStatus, fetchWorkLogs, folderHeartbeat,
  imageHeartbeat, releaseFolder, releaseLock, scanDataset, startFolder, updateImage,
} from './dataset/api'
import type { FolderItem, ImageItem, ReviewStatus } from './dataset/types'

export default function FolderDatasetGrid({ worker }: { worker: string }) {
  const qc = useQueryClient()
  const hotkeyInput = useRef<InputRef>(null)
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [reviewFilter, setReviewFilter] = useState<ReviewStatus | undefined>()
  const [mineOnly, setMineOnly] = useState(false)
  const [changedOnly, setChangedOnly] = useState(false)
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [hotkeyOpen, setHotkeyOpen] = useState(false)
  const [hotkeyValue, setHotkeyValue] = useState('')
  const [nextImageId, setNextImageId] = useState<string | null>(null)
  const [logsOpen, setLogsOpen] = useState(false)
  const [logFolder, setLogFolder] = useState<string | null>(null)

  const folders = useQuery({
    queryKey: ['dataset-folders'],
    queryFn: fetchFolders,
    refetchInterval: 5000,
  })
  const scanStatus = useQuery({
    queryKey: ['scan-status'],
    queryFn: fetchScanStatus,
    refetchInterval: 1500,
  })
  const imageQueryKey = [
    'folder-images', selectedFolder, page, search, reviewFilter, mineOnly, changedOnly,
  ]
  const images = useQuery({
    queryKey: imageQueryKey,
    queryFn: () => fetchFolderImages({
      source_label: selectedFolder,
      page,
      page_size: 48,
      search: search || undefined,
      review_status: reviewFilter,
      actor: mineOnly ? worker : undefined,
      changed_only: changedOnly || undefined,
    }),
    enabled: Boolean(selectedFolder),
    refetchInterval: selectedFolder && !hotkeyOpen ? 5000 : false,
  })
  const hotkeys = useQuery({ queryKey: ['hotkeys'], queryFn: fetchHotkeys, staleTime: 30000 })
  const history = useQuery({
    queryKey: ['history', detail?.image_id],
    queryFn: () => fetchHistory(detail!.image_id),
    enabled: Boolean(detail),
    refetchInterval: detail ? 5000 : false,
  })
  const logs = useQuery({
    queryKey: ['folder-work-logs', logFolder],
    queryFn: () => fetchWorkLogs(logFolder ?? undefined),
    enabled: logsOpen,
  })

  const folderItems: FolderItem[] = folders.data?.items ?? []
  const items = images.data?.items ?? []
  const selectedFolderInfo = folderItems.find((item) => item.folder_name === selectedFolder)
  const detailIndex = detail ? items.findIndex((item) => item.image_id === detail.image_id) : -1
  const hotkeyMap = useMemo(
    () => new Map((hotkeys.data?.items ?? []).map((item) => [item.key, item.label])),
    [hotkeys.data],
  )

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['dataset-folders'] }),
      qc.invalidateQueries({ queryKey: ['folder-images'] }),
      qc.invalidateQueries({ queryKey: ['history'] }),
      qc.invalidateQueries({ queryKey: ['folder-work-logs'] }),
      qc.invalidateQueries({ queryKey: ['summary'] }),
      qc.invalidateQueries({ queryKey: ['scan-status'] }),
    ])
  }

  const resetFilters = () => {
    setSearch('')
    setReviewFilter(undefined)
    setMineOnly(false)
    setChangedOnly(false)
    setPage(1)
  }

  const scan = useMutation({
    mutationFn: scanDataset,
    onSuccess: async (data) => {
      await qc.invalidateQueries({ queryKey: ['scan-status'] })
      message.success(
        data.accepted === false
          ? '이미 스캔이 실행 중입니다.'
          : data.resume
            ? '실패 지점부터 스캔을 재개했습니다.'
            : '스캔 작업을 시작했습니다.',
      )
    },
    onError: () => message.error('스캔 시작에 실패했습니다.'),
  })
  const folderStart = useMutation({
    mutationFn: ({ folder, actor }: { folder: string; actor: string }) => startFolder(folder, actor),
    onSuccess: refresh,
    onError: (error: any) => message.warning(error?.response?.data?.detail?.message ?? '폴더 작업을 시작할 수 없습니다.'),
  })
  const folderRelease = useMutation({
    mutationFn: ({ folder, actor, force }: { folder: string; actor: string; force?: boolean }) => releaseFolder(folder, actor, force),
    onSuccess: async () => { await refresh(); message.success('폴더 작업 상태를 해제했습니다.') },
    onError: (error: any) => message.warning(error?.response?.data?.detail?.message ?? '작업 상태를 해제할 수 없습니다.'),
  })
  const folderComplete = useMutation({
    mutationFn: ({ folder, actor }: { folder: string; actor: string }) => completeFolder(folder, actor),
    onSuccess: async () => { await refresh(); message.success('폴더 작업을 완료 처리했습니다.') },
  })
  const update = useMutation({
    mutationFn: updateImage,
    onSuccess: async (updated) => {
      await refresh()
      if (nextImageId) {
        const refreshed = await fetchFolderImages({
          source_label: selectedFolder,
          page,
          page_size: 48,
          search: search || undefined,
          review_status: reviewFilter,
          actor: mineOnly ? worker : undefined,
          changed_only: changedOnly || undefined,
        })
        qc.setQueryData(imageQueryKey, refreshed)
        const next = refreshed.items.find((item) => item.image_id === nextImageId)
        setNextImageId(null)
        if (next) await openDetail(next)
        else setDetail(null)
      } else setDetail(updated)
      message.success('변경 내용을 저장했습니다.')
    },
    onError: async (error: any) => {
      const payload = error?.response?.data?.detail
      message.error(payload?.message ?? '저장 중 오류가 발생했습니다.')
      setNextImageId(null)
      await refresh()
      if (payload?.item) setDetail(payload.item)
    },
  })
  const remove = useMutation({
    mutationFn: backupDelete,
    onSuccess: async () => { setDetail(null); await refresh(); message.success('이미지를 백업 폴더로 이동했습니다.') },
    onError: (error: any) => message.error(error?.response?.data?.detail?.message ?? '삭제 중 오류가 발생했습니다.'),
  })

  const openLogs = (folder?: string) => {
    setLogFolder(folder ?? null)
    setLogsOpen(true)
  }
  const openFolder = async (folder: FolderItem) => {
    try {
      if (folder.work_status !== 'completed' && (!folder.working_by || folder.working_by === worker)) {
        await folderStart.mutateAsync({ folder: folder.folder_name, actor: worker })
      }
    } catch { /* 다른 작업자가 작업 중이면 읽기 전용으로 진입 */ }
    setSelectedFolder(folder.folder_name)
    setDetail(null)
    resetFilters()
  }
  const openDetail = async (item: ImageItem) => {
    if (detail?.locked_by === worker && detail.image_id !== item.image_id) {
      await releaseLock(detail.image_id, worker).catch(() => undefined)
    }
    try { setDetail(await acquireLock(item.image_id, worker)) }
    catch (error: any) {
      const payload = error?.response?.data?.detail
      message.warning(payload?.message ?? '이미지를 잠글 수 없습니다.')
      if (payload?.item) setDetail(payload.item)
    }
  }
  const closeDetail = async () => {
    if (detail?.locked_by === worker) await releaseLock(detail.image_id, worker).catch(() => undefined)
    setDetail(null)
  }
  const leaveFolder = async () => {
    await closeDetail()
    setSelectedFolder(null)
    resetFilters()
  }
  const moveDetail = async (offset: number) => {
    if (detailIndex < 0) return
    const next = items[detailIndex + offset]
    if (next) await openDetail(next)
  }
  const applyLabel = (label: string, moveNext: boolean) => {
    if (!detail) return
    if (detail.locked_by && detail.locked_by !== worker) {
      message.warning(`${detail.locked_by}님이 검수 중입니다.`)
      return
    }
    const next = moveNext ? items[detailIndex + 1] : undefined
    setNextImageId(next?.image_id ?? null)
    update.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version, label })
  }
  const applyHotkey = () => {
    const label = hotkeyMap.get(hotkeyValue.trim())
    if (!label) { message.error('등록되지 않은 핫키 번호입니다.'); return }
    applyLabel(label, true)
    setHotkeyOpen(false)
    setHotkeyValue('')
  }
  const resetDetailForFilter = async () => {
    await closeDetail()
    setPage(1)
  }

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      if (event.key === 'Enter' && detail && (!detail.locked_by || detail.locked_by === worker)) {
        event.preventDefault()
        setHotkeyOpen(true)
      }
      if (event.key === 'ArrowLeft' && detail) void moveDetail(-1)
      if (event.key === 'ArrowRight' && detail) void moveDetail(1)
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [detail, detailIndex, items, worker])
  useEffect(() => { if (hotkeyOpen) setTimeout(() => hotkeyInput.current?.focus(), 50) }, [hotkeyOpen])
  useEffect(() => {
    if (!detail || detail.locked_by !== worker) return
    const timer = window.setInterval(() => { void imageHeartbeat(detail.image_id, worker) }, 60000)
    return () => window.clearInterval(timer)
  }, [detail?.image_id, detail?.locked_by, worker])
  useEffect(() => {
    if (!selectedFolder || selectedFolderInfo?.working_by !== worker) return
    void folderHeartbeat(selectedFolder, worker)
    const timer = window.setInterval(() => {
      void folderHeartbeat(selectedFolder, worker).then(() => qc.invalidateQueries({ queryKey: ['dataset-folders'] }))
    }, 60000)
    return () => window.clearInterval(timer)
  }, [selectedFolder, selectedFolderInfo?.working_by, worker])

  return <>
    {!selectedFolder ? <DatasetDashboard
      folders={folderItems}
      scanStatus={scanStatus.data}
      scanPending={scan.isPending}
      onScan={(mode) => scan.mutate(mode)}
      onOpenFolder={(folder) => void openFolder(folder)}
      onOpenLogs={openLogs}
      onForceRelease={(folder) => folderRelease.mutate({ folder: folder.folder_name, actor: worker, force: true })}
    /> : <FolderReviewView
      worker={worker}
      folder={selectedFolder}
      folderInfo={selectedFolderInfo}
      images={items}
      total={images.data?.total ?? 0}
      page={page}
      detail={detail}
      detailIndex={detailIndex}
      hotkeys={hotkeys.data?.items ?? []}
      history={history.data?.items ?? []}
      search={search}
      reviewFilter={reviewFilter}
      mineOnly={mineOnly}
      changedOnly={changedOnly}
      hotkeyOpen={hotkeyOpen}
      hotkeyValue={hotkeyValue}
      hotkeyInput={hotkeyInput}
      loading={images.isLoading}
      onBack={() => void leaveFolder()}
      onSearch={(value) => { setSearch(value); void resetDetailForFilter() }}
      onReviewFilter={(value) => { setReviewFilter(value); void resetDetailForFilter() }}
      onMineOnly={(value) => { setMineOnly(value); void resetDetailForFilter() }}
      onChangedOnly={(value) => { setChangedOnly(value); void resetDetailForFilter() }}
      onResetFilters={() => { resetFilters(); void closeDetail() }}
      onOpenLogs={() => openLogs(selectedFolder)}
      onCompleteFolder={() => folderComplete.mutate({ folder: selectedFolder, actor: worker })}
      onReleaseFolder={(force) => folderRelease.mutate({ folder: selectedFolder, actor: worker, force })}
      onOpenDetail={(item) => void openDetail(item)}
      onCloseDetail={() => void closeDetail()}
      onMoveDetail={(offset) => void moveDetail(offset)}
      onApplyLabel={applyLabel}
      onDelete={() => detail && remove.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version })}
      onPage={(value) => { setPage(value); void closeDetail() }}
      onHotkeyOpen={setHotkeyOpen}
      onHotkeyValue={setHotkeyValue}
      onApplyHotkey={applyHotkey}
    />}

    <WorkLogModal
      open={logsOpen}
      folder={logFolder}
      items={logs.data?.items ?? []}
      loading={logs.isLoading}
      onClose={() => setLogsOpen(false)}
    />
  </>
}
