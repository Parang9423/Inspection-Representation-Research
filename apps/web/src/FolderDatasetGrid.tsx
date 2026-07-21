import { useEffect, useMemo, useRef, useState } from 'react'
import type { InputRef } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Button, Card, Col, Empty, Form, Image, Input, Modal, Pagination,
  Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tag, Typography, message,
} from 'antd'
import {
  ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, FolderOpenOutlined,
  FolderOutlined, LeftOutlined, LockOutlined, ReloadOutlined, RightOutlined,
  StopOutlined, SyncOutlined,
} from '@ant-design/icons'
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })
type SplitCode = 'unassigned' | 'train' | 'valid' | 'test'
type ReviewStatus = 'unreviewed' | 'reviewing' | 'reviewed'
type FolderWorkStatus = 'idle' | 'working' | 'completed'

interface FolderItem {
  folder_name: string
  image_count: number
  reviewed_count: number
  reviewing_count: number
  work_status: FolderWorkStatus
  working_by?: string | null
  working_at?: string | null
  progress: number
}

interface ImageItem {
  image_id: string
  filename: string
  source_label: string
  label: string
  split: SplitCode
  status: string
  image_url: string
  cam_url: string
  version: number
  assigned_to?: string | null
  review_status: ReviewStatus
  reviewed_by?: string | null
  reviewed_at?: string | null
  locked_by?: string | null
  locked_at?: string | null
}

async function fetchFolders() {
  return (await api.get<{ items: FolderItem[] }>('/folder-work/folders')).data
}
async function fetchFolderImages(params: Record<string, unknown>) {
  return (await api.get<{ items: ImageItem[]; total: number }>('/collaboration/folder-images', { params })).data
}
async function fetchHotkeys() {
  return (await api.get<{ items: Array<{ key: string; label: string }> }>('/labels/hotkeys')).data
}
async function scanDataset(mode: 'quick' | 'full') {
  return (await api.post(`/scan/${mode}`)).data
}
async function startFolder(folder: string, actor: string) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/start`, { actor })).data
}
async function releaseFolder(folder: string, actor: string, force = false) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/release`, { actor, force })).data
}
async function completeFolder(folder: string, actor: string) {
  return (await api.post(`/folder-work/folders/${encodeURIComponent(folder)}/complete`, { actor })).data
}
async function fetchHistory(imageId: string) {
  return (await api.get<{ items: Array<Record<string, unknown>> }>(`/collaboration/images/${imageId}/history`)).data
}
async function acquireLock(imageId: string, actor: string) {
  return (await api.post<ImageItem>(`/collaboration/images/${imageId}/lock`, { actor })).data
}
async function releaseLock(imageId: string, actor: string) {
  return (await api.post(`/collaboration/images/${imageId}/unlock`, { actor })).data
}
async function heartbeat(imageId: string, actor: string) {
  return (await api.post(`/collaboration/images/${imageId}/heartbeat`, { actor })).data
}
async function updateImage(payload: { image_id: string; actor: string; expected_version: number; label: string }) {
  return (await api.patch<ImageItem>('/collaboration/images/update', payload)).data
}
async function backupDelete(payload: { image_id: string; actor: string; expected_version: number }) {
  return (await api.post<{ moved: number }>('/collaboration/images/backup-delete', payload)).data
}

const folderStatusMeta: Record<FolderWorkStatus, { label: string; color: string }> = {
  idle: { label: '미작업', color: 'default' },
  working: { label: '작업중', color: 'orange' },
  completed: { label: '완료', color: 'green' },
}

export default function FolderDatasetGrid({ worker }: { worker: string }) {
  const qc = useQueryClient()
  const hotkeyInput = useRef<InputRef>(null)
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [hotkeyOpen, setHotkeyOpen] = useState(false)
  const [hotkeyValue, setHotkeyValue] = useState('')
  const [nextImageId, setNextImageId] = useState<string | null>(null)

  const folders = useQuery({ queryKey: ['dataset-folders'], queryFn: fetchFolders, refetchInterval: 5000 })
  const images = useQuery({
    queryKey: ['folder-images', selectedFolder, page, search],
    queryFn: () => fetchFolderImages({ source_label: selectedFolder, page, page_size: 48, search: search || undefined }),
    enabled: !!selectedFolder,
    refetchInterval: selectedFolder && !hotkeyOpen ? 5000 : false,
  })
  const hotkeys = useQuery({ queryKey: ['hotkeys'], queryFn: fetchHotkeys, staleTime: 30000 })
  const history = useQuery({
    queryKey: ['history', detail?.image_id],
    queryFn: () => fetchHistory(detail!.image_id), enabled: !!detail, refetchInterval: detail ? 5000 : false,
  })

  const items = images.data?.items ?? []
  const folderItems = folders.data?.items ?? []
  const selectedFolderInfo = folderItems.find((item) => item.folder_name === selectedFolder)
  const detailIndex = detail ? items.findIndex((item) => item.image_id === detail.image_id) : -1
  const hotkeyMap = useMemo(() => new Map((hotkeys.data?.items ?? []).map((item) => [item.key, item.label])), [hotkeys.data])

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['dataset-folders'] }),
      qc.invalidateQueries({ queryKey: ['folder-images'] }),
      qc.invalidateQueries({ queryKey: ['history'] }),
      qc.invalidateQueries({ queryKey: ['summary'] }),
    ])
  }

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

  const openFolder = async (folder: FolderItem) => {
    try {
      if (folder.work_status !== 'completed' && (!folder.working_by || folder.working_by === worker)) {
        await folderStart.mutateAsync({ folder: folder.folder_name, actor: worker })
      }
    } catch { /* 읽기 전용 진입 허용 */ }
    setSelectedFolder(folder.folder_name)
    setPage(1); setSearch(''); setDetail(null)
  }

  const openDetail = async (item: ImageItem) => {
    if (detail?.locked_by === worker && detail.image_id !== item.image_id) await releaseLock(detail.image_id, worker).catch(() => undefined)
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
  const leaveFolder = async () => { await closeDetail(); setSelectedFolder(null); setPage(1); setSearch('') }

  const update = useMutation({
    mutationFn: updateImage,
    onSuccess: async (updated) => {
      await refresh()
      if (nextImageId) {
        const refreshed = await fetchFolderImages({ source_label: selectedFolder, page, page_size: 48, search: search || undefined })
        qc.setQueryData(['folder-images', selectedFolder, page, search], refreshed)
        const next = refreshed.items.find((item) => item.image_id === nextImageId)
        setNextImageId(null)
        if (next) await openDetail(next); else setDetail(null)
      } else setDetail(updated)
      message.success('변경 내용을 저장했습니다.')
    },
    onError: async (error: any) => {
      const payload = error?.response?.data?.detail
      message.error(payload?.message ?? '저장 중 오류가 발생했습니다.')
      setNextImageId(null); await refresh(); if (payload?.item) setDetail(payload.item)
    },
  })
  const remove = useMutation({
    mutationFn: backupDelete,
    onSuccess: async () => { setDetail(null); await refresh(); message.success('이미지를 백업 폴더로 이동했습니다.') },
  })
  const scan = useMutation({
    mutationFn: scanDataset,
    onSuccess: (data) => message.success(data.accepted === false ? '이미 스캔이 실행 중입니다.' : '스캔 작업을 시작했습니다.'),
    onError: () => message.error('스캔 시작에 실패했습니다.'),
  })

  const moveDetail = async (offset: number) => {
    if (detailIndex < 0) return
    const next = items[detailIndex + offset]
    if (next) await openDetail(next)
  }
  const applyLabel = (label: string, moveNext: boolean) => {
    if (!detail) return
    if (detail.locked_by && detail.locked_by !== worker) { message.warning(`${detail.locked_by}님이 검수 중입니다.`); return }
    const next = moveNext ? items[detailIndex + 1] : undefined
    setNextImageId(next?.image_id ?? null)
    update.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version, label })
  }
  const applyHotkey = () => {
    const label = hotkeyMap.get(hotkeyValue.trim())
    if (!label) { message.error('등록되지 않은 핫키 번호입니다.'); return }
    applyLabel(label, true); setHotkeyOpen(false); setHotkeyValue('')
  }

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      if (event.key === 'Enter' && detail && (!detail.locked_by || detail.locked_by === worker)) { event.preventDefault(); setHotkeyOpen(true) }
      if (event.key === 'ArrowLeft' && detail) void moveDetail(-1)
      if (event.key === 'ArrowRight' && detail) void moveDetail(1)
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [detail, detailIndex, items, worker])
  useEffect(() => { if (hotkeyOpen) setTimeout(() => hotkeyInput.current?.focus(), 50) }, [hotkeyOpen])
  useEffect(() => {
    if (!detail || detail.locked_by !== worker) return
    const timer = window.setInterval(() => { void heartbeat(detail.image_id, worker) }, 60000)
    return () => window.clearInterval(timer)
  }, [detail?.image_id, detail?.locked_by, worker])

  if (!selectedFolder) {
    const total = folderItems.reduce((sum, item) => sum + item.image_count, 0)
    return <>
      <Row gutter={16} className="stats-row">
        <Col flex="1"><Card><Statistic title="원본 폴더 수" value={folderItems.length} /></Card></Col>
        <Col flex="1"><Card><Statistic title="전체 이미지" value={total} /></Card></Col>
      </Row>
      <Card className="toolbar"><Space wrap>
        <Button icon={<SyncOutlined />} loading={scan.isPending} onClick={() => scan.mutate('quick')}>빠른 증분 스캔</Button>
        <Popconfirm title="전체 파일의 변경·삭제 상태까지 다시 확인합니다." okText="실행" cancelText="취소" onConfirm={() => scan.mutate('full')}>
          <Button icon={<ReloadOutlined />}>전체 재스캔</Button>
        </Popconfirm>
        <Typography.Text type="secondary">기본 스캔은 DB에 없는 신규 파일만 추가합니다.</Typography.Text>
      </Space></Card>
      {folderItems.length ? <div className="folder-grid">
        {folderItems.map((folder) => {
          const meta = folderStatusMeta[folder.work_status]
          return <Card key={folder.folder_name} hoverable className={`folder-card folder-${folder.work_status}`} onClick={() => void openFolder(folder)}>
            <div className="folder-card-header">
              <div className="folder-card-icon"><FolderOutlined /></div>
              <Tag color={meta.color}>{meta.label}</Tag>
            </div>
            <Typography.Title level={5} ellipsis={{ tooltip: folder.folder_name }}>{folder.folder_name}</Typography.Title>
            <Space wrap>
              <Tag color="blue">이미지 {folder.image_count}</Tag>
              <Tag color="green">완료 {folder.reviewed_count}</Tag>
              {folder.reviewing_count > 0 && <Tag color="orange">검수중 {folder.reviewing_count}</Tag>}
            </Space>
            {folder.working_by && <Typography.Text type="secondary">작업자: {folder.working_by}</Typography.Text>}
            <Progress percent={Math.round(folder.progress)} size="small" status={folder.work_status === 'completed' ? 'success' : 'active'} />
            <Space className="folder-card-actions" onClick={(event) => event.stopPropagation()}>
              <Button type="link" icon={<FolderOpenOutlined />} onClick={() => void openFolder(folder)}>열기</Button>
              {folder.work_status === 'working' && (
                <Popconfirm title={`${folder.working_by ?? '현재 작업자'}의 작업 상태를 해제할까요?`} okText="해제" cancelText="취소" onConfirm={() => folderRelease.mutate({ folder: folder.folder_name, actor: worker, force: true })}>
                  <Button type="link" danger icon={<StopOutlined />}>강제 해제</Button>
                </Popconfirm>
              )}
            </Space>
          </Card>
        })}
      </div> : <Empty description="인식된 폴더가 없습니다." />}
    </>
  }

  const folderReadOnly = !!selectedFolderInfo?.working_by && selectedFolderInfo.working_by !== worker
  return <>
    <Card className="toolbar folder-toolbar"><Space wrap>
      <Button icon={<ArrowLeftOutlined />} onClick={() => void leaveFolder()}>폴더 목록</Button>
      <Typography.Title level={4} style={{ margin: 0 }}>{selectedFolder}</Typography.Title>
      <Tag color={folderStatusMeta[selectedFolderInfo?.work_status ?? 'idle'].color}>{folderStatusMeta[selectedFolderInfo?.work_status ?? 'idle'].label}</Tag>
      {selectedFolderInfo?.working_by && <Tag color="orange">작업자 {selectedFolderInfo.working_by}</Tag>}
      <Tag color="blue">{images.data?.total ?? 0}개</Tag>
      <Input.Search placeholder="파일명·현재 라벨 검색" allowClear onSearch={(value) => { setSearch(value); setPage(1); void closeDetail() }} style={{ width: 260 }} />
      {!folderReadOnly && <Button icon={<CheckCircleOutlined />} onClick={() => folderComplete.mutate({ folder: selectedFolder, actor: worker })}>폴더 완료</Button>}
      {selectedFolderInfo?.work_status === 'working' && <Button danger icon={<StopOutlined />} onClick={() => folderRelease.mutate({ folder: selectedFolder, actor: worker, force: folderReadOnly })}>작업 상태 해제</Button>}
    </Space></Card>
    {folderReadOnly && <Alert type="warning" showIcon message={`${selectedFolderInfo?.working_by}님이 이 폴더를 작업 중입니다.`} description="이미지 조회는 가능하지만 다른 작업자가 잠근 이미지는 수정할 수 없습니다." style={{ marginBottom: 12 }} />}

    <div className={detail ? 'dataset-review detail-open' : 'dataset-review'}>
      {detail && <aside className="detail-pane">
        <div className="detail-header"><div><Typography.Title level={4}>클래스 검수</Typography.Title><Typography.Text type="secondary">{detail.filename}</Typography.Text></div><Button onClick={() => void closeDetail()}>닫기</Button></div>
        {detail.locked_by && detail.locked_by !== worker && <Alert type="warning" showIcon icon={<LockOutlined />} message={`${detail.locked_by}님이 검수 중입니다.`} style={{ marginBottom: 12 }} />}
        <div className="detail-image-wrap"><Image src={detail.image_url} preview /></div>
        <Space className="detail-navigation"><Button icon={<LeftOutlined />} disabled={detailIndex <= 0} onClick={() => void moveDetail(-1)}>이전</Button><Typography.Text>{detailIndex >= 0 ? detailIndex + 1 : '-'} / {items.length}</Typography.Text><Button icon={<RightOutlined />} disabled={detailIndex < 0 || detailIndex >= items.length - 1} onClick={() => void moveDetail(1)}>다음</Button></Space>
        <Form layout="vertical"><Form.Item label="현재 클래스"><Select showSearch value={detail.label} disabled={!!detail.locked_by && detail.locked_by !== worker} options={(hotkeys.data?.items ?? []).map((item) => ({ value: item.label, label: `${item.key} · ${item.label}` }))} onChange={(label) => applyLabel(label, false)} /></Form.Item></Form>
        <Space wrap style={{ marginBottom: 12 }}><Tag color="blue">version {detail.version}</Tag><Tag className={`status-tag status-${detail.review_status}`}>{detail.review_status}</Tag>{detail.reviewed_by && <Tag color="green">검수: {detail.reviewed_by}</Tag>}{detail.locked_by && <Tag color="orange">잠금: {detail.locked_by}</Tag>}</Space>
        <Card size="small" title="클래스 핫키" className="hotkey-card"><div className="hotkey-list">{(hotkeys.data?.items ?? []).map((item) => <Tag key={item.key} onClick={() => applyLabel(item.label, true)}>{item.key} · {item.label}</Tag>)}</div></Card>
        <Card size="small" title="변경 이력" className="history-card"><Table size="small" pagination={false} rowKey="history_id" dataSource={history.data?.items ?? []} columns={[{ title: '이전', dataIndex: 'previous_label', ellipsis: true }, { title: '변경', dataIndex: 'new_label', ellipsis: true }, { title: '작업자', dataIndex: 'changed_by', width: 90 }, { title: '시간', dataIndex: 'changed_at', width: 150 }]} /></Card>
        <Popconfirm title="이미지를 백업 폴더로 이동할까요?" okText="이동" cancelText="취소" disabled={!!detail.locked_by && detail.locked_by !== worker} onConfirm={() => remove.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version })}><Button danger icon={<DeleteOutlined />} block disabled={!!detail.locked_by && detail.locked_by !== worker}>데이터 삭제(백업 이동)</Button></Popconfirm>
      </aside>}
      <section className="grid-pane">
        {items.length ? <div className="image-grid">{items.map((item) => {
          const ownerClass = item.locked_by === worker ? 'mine' : item.locked_by ? 'locked' : ''
          return <Card key={item.image_id} hoverable className={`image-card review-${item.review_status} ${ownerClass} ${detail?.image_id === item.image_id ? 'selected' : ''}`} cover={<div className="thumb-wrap"><img src={item.image_url} alt={item.filename} /><span className={`review-badge badge-${item.review_status}`}>{item.review_status === 'reviewed' ? '완료' : item.review_status === 'reviewing' ? '작업중' : '미검수'}</span>{item.locked_by && <span className="lock-badge"><LockOutlined /> {item.locked_by}</span>}</div>} onClick={() => void openDetail(item)}>
            <Card.Meta title={item.filename} description={<Space direction="vertical" size={2}><Typography.Text>{item.label}</Typography.Text><Typography.Text type="secondary">{item.review_status === 'reviewed' ? `검수: ${item.reviewed_by ?? '-'}` : item.locked_by ? `작업: ${item.locked_by}` : '미검수'}</Typography.Text></Space>} />
          </Card>
        })}</div> : <Empty description="이 폴더에 표시할 이미지가 없습니다." />}
        <Pagination current={page} pageSize={48} total={images.data?.total ?? 0} showSizeChanger={false} onChange={(value) => { setPage(value); void closeDetail() }} />
      </section>
    </div>

    <Modal title="클래스 핫키 입력" open={hotkeyOpen} onCancel={() => { setHotkeyOpen(false); setHotkeyValue('') }} onOk={applyHotkey} okText="라벨 변경" cancelText="취소">
      <Input ref={hotkeyInput} value={hotkeyValue} onChange={(event) => setHotkeyValue(event.target.value.replace(/\D/g, ''))} onPressEnter={applyHotkey} placeholder="예: 1" inputMode="numeric" size="large" />
      <div className="hotkey-modal-list">{(hotkeys.data?.items ?? []).map((item) => <Tag key={item.key}>{item.key} · {item.label}</Tag>)}</div>
    </Modal>
  </>
}
