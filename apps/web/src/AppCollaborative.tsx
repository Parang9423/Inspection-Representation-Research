import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { InputRef } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Layout,
  Menu,
  Modal,
  Pagination,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  DatabaseOutlined,
  DeleteOutlined,
  ExportOutlined,
  LeftOutlined,
  LockOutlined,
  ReloadOutlined,
  RightOutlined,
  SplitCellsOutlined,
  UserOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import './collaborative.css'

const { Header, Sider, Content } = Layout
const api = axios.create({ baseURL: '/api' })
const WORKER_KEY = 'aoi-dataset-worker'

type SplitCode = 'unassigned' | 'train' | 'valid' | 'test'
type ReviewStatus = 'unreviewed' | 'reviewing' | 'reviewed'

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

interface Summary {
  totals: Record<string, number>
  classes: Array<{ label: string; train: number; valid: number; test: number; unassigned: number; total: number }>
}

const splitOptions = [
  { value: 'unassigned', label: '미지정' },
  { value: 'train', label: '학습' },
  { value: 'valid', label: '검증' },
  { value: 'test', label: '시험' },
]

async function fetchImages(params: Record<string, unknown>) {
  return (await api.get<{ items: ImageItem[]; total: number }>('/images', { params })).data
}
async function fetchSummary() { return (await api.get<Summary>('/summary')).data }
async function fetchHotkeys() { return (await api.get<{ items: Array<{ key: string; label: string }> }>('/labels/hotkeys')).data }
async function scanDataset() { return (await api.post('/scan')).data }
async function fetchHistory(imageId: string) { return (await api.get<{ items: Array<Record<string, unknown>> }>(`/collaboration/images/${imageId}/history`)).data }
async function acquireLock(imageId: string, actor: string) { return (await api.post<ImageItem>(`/collaboration/images/${imageId}/lock`, { actor })).data }
async function releaseLock(imageId: string, actor: string) { return (await api.post(`/collaboration/images/${imageId}/unlock`, { actor })).data }
async function heartbeat(imageId: string, actor: string) { return (await api.post(`/collaboration/images/${imageId}/heartbeat`, { actor })).data }
async function updateImage(payload: { image_id: string; actor: string; expected_version: number; label?: string; split?: SplitCode }) {
  return (await api.patch<ImageItem>('/collaboration/images/update', payload)).data
}
async function backupDelete(payload: { image_id: string; actor: string; expected_version: number }) {
  return (await api.post<{ moved: number }>('/collaboration/images/backup-delete', payload)).data
}
async function autoSplit(payload: { train_ratio: number; valid_ratio: number; test_ratio: number; seed: number; only_unassigned: boolean }) {
  return (await api.post('/splits/auto', payload)).data
}
async function exportDataset(payload: { dataset_name: string; mode: 'copy' | 'hardlink' | 'manifest' }) {
  return (await api.post('/exports', payload)).data
}

function AppContent() {
  const [menu, setMenu] = useState('dataset')
  const [worker, setWorker] = useState(localStorage.getItem(WORKER_KEY) ?? '')
  const [workerDraft, setWorkerDraft] = useState(worker)
  const [workerOpen, setWorkerOpen] = useState(!worker)

  const saveWorker = () => {
    const value = workerDraft.trim()
    if (!value) return message.error('작업자 이름을 입력하세요.')
    localStorage.setItem(WORKER_KEY, value)
    setWorker(value)
    setWorkerOpen(false)
  }

  const content: Record<string, ReactNode> = {
    dataset: <DatasetGrid worker={worker} />,
    summary: <SummaryTable />,
    split: <TrainSplitPanel worker={worker} />,
    export: <ExportPanel />,
  }

  return (
    <>
      <Layout className="app-layout">
        <Sider width={228} theme="light">
          <div className="brand"><DatabaseOutlined /> AOI Dataset</div>
          <Menu
            mode="inline"
            selectedKeys={[menu]}
            onClick={({ key }) => setMenu(key)}
            items={[
              { key: 'dataset', icon: <DatabaseOutlined />, label: '데이터셋' },
              { key: 'summary', icon: <DatabaseOutlined />, label: '클래스 현황' },
              { key: 'split', icon: <SplitCellsOutlined />, label: 'Train Split' },
              { key: 'export', icon: <ExportOutlined />, label: '데이터 내보내기' },
            ]}
          />
        </Sider>
        <Layout>
          <Header className="header collaborative-header">
            <div>
              <Typography.Title level={3}>AOI 학습 데이터셋 관리자</Typography.Title>
              <Typography.Text type="secondary">동시 검수 · 충돌 방지 · 변경 이력</Typography.Text>
            </div>
            <Button icon={<UserOutlined />} onClick={() => setWorkerOpen(true)}>작업자: {worker || '미설정'}</Button>
          </Header>
          <Content className="content">{worker ? content[menu] : <Empty description="작업자를 설정하세요." />}</Content>
        </Layout>
      </Layout>
      <Modal title="작업자 설정" open={workerOpen} closable={!!worker} maskClosable={false} onCancel={() => worker && setWorkerOpen(false)} onOk={saveWorker} okText="적용">
        <Input value={workerDraft} onChange={(event) => setWorkerDraft(event.target.value)} onPressEnter={saveWorker} placeholder="예: 조동일" prefix={<UserOutlined />} autoFocus />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>작업자 이름은 이미지 잠금과 변경 이력에 저장됩니다.</Typography.Paragraph>
      </Modal>
    </>
  )
}

function DatasetGrid({ worker }: { worker: string }) {
  const qc = useQueryClient()
  const hotkeyInput = useRef<InputRef>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [hotkeyOpen, setHotkeyOpen] = useState(false)
  const [hotkeyValue, setHotkeyValue] = useState('')
  const [nextImageId, setNextImageId] = useState<string | null>(null)

  const images = useQuery({ queryKey: ['images', page, search], queryFn: () => fetchImages({ page, page_size: 48, search: search || undefined }), refetchInterval: hotkeyOpen ? false : 5000 })
  const summary = useQuery({ queryKey: ['summary'], queryFn: fetchSummary, refetchInterval: 5000 })
  const hotkeys = useQuery({ queryKey: ['hotkeys'], queryFn: fetchHotkeys, staleTime: 30000 })
  const history = useQuery({ queryKey: ['history', detail?.image_id], queryFn: () => fetchHistory(detail!.image_id), enabled: !!detail, refetchInterval: detail ? 5000 : false })
  const items = images.data?.items ?? []
  const detailIndex = detail ? items.findIndex((item) => item.image_id === detail.image_id) : -1
  const hotkeyMap = useMemo(() => new Map((hotkeys.data?.items ?? []).map((item) => [item.key, item.label])), [hotkeys.data])

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['images'] }),
      qc.invalidateQueries({ queryKey: ['summary'] }),
      qc.invalidateQueries({ queryKey: ['history'] }),
    ])
  }

  const openDetail = async (item: ImageItem) => {
    if (detail?.locked_by === worker && detail.image_id !== item.image_id) await releaseLock(detail.image_id, worker).catch(() => undefined)
    try {
      setDetail(await acquireLock(item.image_id, worker))
    } catch (error: any) {
      const payload = error?.response?.data?.detail
      message.warning(payload?.message ?? '이미지를 잠글 수 없습니다.')
      if (payload?.item) setDetail(payload.item)
    }
  }

  const closeDetail = async () => {
    if (detail?.locked_by === worker) await releaseLock(detail.image_id, worker).catch(() => undefined)
    setDetail(null)
  }

  const update = useMutation({
    mutationFn: updateImage,
    onSuccess: async (updated) => {
      await refresh()
      if (nextImageId) {
        const cached = qc.getQueryData<{ items: ImageItem[]; total: number }>(['images', page, search])
        const next = cached?.items.find((item) => item.image_id === nextImageId)
        setNextImageId(null)
        if (next) await openDetail(next)
        else setDetail(null)
      } else setDetail(updated)
      message.success('변경 내용을 저장했습니다.')
    },
    onError: async (error: any) => {
      const payload = error?.response?.data?.detail
      if (error?.response?.status === 409) message.error('다른 작업자가 먼저 수정했습니다. 최신 데이터를 다시 불러왔습니다.')
      else if (error?.response?.status === 423) message.warning(payload?.message ?? '다른 작업자가 검수 중입니다.')
      else message.error(payload?.message ?? '저장 중 오류가 발생했습니다.')
      setNextImageId(null)
      await refresh()
      if (payload?.item) setDetail(payload.item)
    },
  })

  const remove = useMutation({
    mutationFn: backupDelete,
    onSuccess: async () => { setDetail(null); await refresh(); message.success('이미지를 백업 폴더로 이동했습니다.') },
    onError: (error: any) => message.error(error?.response?.data?.detail?.message ?? '삭제 중 충돌이 발생했습니다.'),
  })
  const scan = useMutation({ mutationFn: scanDataset, onSuccess: async (data) => { await refresh(); message.success(`${data.count}개 이미지를 동기화했습니다.`) } })

  const moveDetail = async (offset: number) => {
    if (detailIndex < 0) return
    const next = items[detailIndex + offset]
    if (next) await openDetail(next)
  }

  const applyLabel = (label: string, moveNext: boolean) => {
    if (!detail) return
    if (detail.locked_by && detail.locked_by !== worker) return message.warning(`${detail.locked_by}님이 검수 중입니다.`)
    const next = moveNext ? items[detailIndex + 1] : undefined
    setNextImageId(next?.image_id ?? null)
    update.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version, label })
  }

  const applyHotkey = () => {
    const label = hotkeyMap.get(hotkeyValue.trim())
    if (!label) return message.error('등록되지 않은 핫키 번호입니다.')
    applyLabel(label, true)
    setHotkeyOpen(false)
    setHotkeyValue('')
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

  return (
    <>
      <Row gutter={16} className="stats-row">
        <Col flex="1"><Card><Statistic title="전체 이미지" value={summary.data?.totals.total ?? 0} /></Card></Col>
        <Col flex="1"><Card><Statistic title="클래스 수" value={summary.data?.classes.length ?? 0} /></Card></Col>
        <Col flex="1"><Card><Statistic title="검수 완료" value={summary.data?.totals.reviewed ?? 0} /></Card></Col>
        <Col flex="1"><Card><Statistic title="검수 중" value={summary.data?.totals.reviewing ?? 0} /></Card></Col>
      </Row>
      <Card className="toolbar"><Space wrap>
        <Input.Search placeholder="파일명·라벨 검색" allowClear onSearch={(value) => { setSearch(value); setPage(1); void closeDetail() }} style={{ width: 300 }} />
        <Button icon={<ReloadOutlined />} loading={scan.isPending} onClick={() => scan.mutate()}>폴더 다시 스캔</Button>
        <Typography.Text type="secondary">5초 자동 동기화 · 상세 선택 시 10분 잠금 · Enter 핫키</Typography.Text>
      </Space></Card>

      <div className={detail ? 'dataset-review detail-open' : 'dataset-review'}>
        {detail && <aside className="detail-pane">
          <div className="detail-header"><div><Typography.Title level={4}>클래스 검수</Typography.Title><Typography.Text type="secondary">{detail.filename}</Typography.Text></div><Button onClick={() => void closeDetail()}>닫기</Button></div>
          {detail.locked_by && detail.locked_by !== worker && <Alert type="warning" showIcon icon={<LockOutlined />} message={`${detail.locked_by}님이 검수 중입니다.`} description="조회만 가능하며 수정은 차단됩니다." style={{ marginBottom: 12 }} />}
          <div className="detail-image-wrap"><Image src={detail.image_url} preview /></div>
          <Space className="detail-navigation">
            <Button icon={<LeftOutlined />} disabled={detailIndex <= 0} onClick={() => void moveDetail(-1)}>이전</Button>
            <Typography.Text>{detailIndex >= 0 ? detailIndex + 1 : '-'} / {items.length}</Typography.Text>
            <Button icon={<RightOutlined />} disabled={detailIndex < 0 || detailIndex >= items.length - 1} onClick={() => void moveDetail(1)}>다음</Button>
          </Space>
          <Form layout="vertical"><Form.Item label="현재 클래스"><Select showSearch value={detail.label} disabled={!!detail.locked_by && detail.locked_by !== worker} options={(hotkeys.data?.items ?? []).map((item) => ({ value: item.label, label: `${item.key} · ${item.label}` }))} onChange={(label) => applyLabel(label, false)} /></Form.Item></Form>
          <Space wrap style={{ marginBottom: 12 }}><Tag color="blue">version {detail.version}</Tag><Tag>{detail.review_status}</Tag>{detail.reviewed_by && <Tag color="green">검수: {detail.reviewed_by}</Tag>}{detail.locked_by && <Tag color="orange">잠금: {detail.locked_by}</Tag>}</Space>
          <Card size="small" title="클래스 핫키" className="hotkey-card"><div className="hotkey-list">{(hotkeys.data?.items ?? []).map((item) => <Tag key={item.key} onClick={() => applyLabel(item.label, true)}>{item.key} · {item.label}</Tag>)}</div></Card>
          <Card size="small" title="변경 이력" className="history-card"><Table size="small" pagination={false} rowKey="history_id" dataSource={history.data?.items ?? []} columns={[{ title: '이전', dataIndex: 'previous_label', ellipsis: true },{ title: '변경', dataIndex: 'new_label', ellipsis: true },{ title: '작업자', dataIndex: 'changed_by', width: 90 },{ title: '시간', dataIndex: 'changed_at', width: 150 }]} /></Card>
          <Popconfirm title="이미지를 백업 폴더로 이동할까요?" description="DB에서 제거되고 원본 파일은 backup_image로 이동합니다." okText="이동" cancelText="취소" disabled={!!detail.locked_by && detail.locked_by !== worker} onConfirm={() => remove.mutate({ image_id: detail.image_id, actor: worker, expected_version: detail.version })}><Button danger icon={<DeleteOutlined />} block disabled={!!detail.locked_by && detail.locked_by !== worker} loading={remove.isPending}>데이터 삭제(백업 이동)</Button></Popconfirm>
        </aside>}

        <section className="grid-pane">
          {items.length ? <div className="image-grid">{items.map((item) => <Card key={item.image_id} hoverable className={detail?.image_id === item.image_id ? 'image-card selected' : 'image-card'} cover={<div className="thumb-wrap"><img src={item.image_url} alt={item.filename} />{item.locked_by && <span className="lock-badge"><LockOutlined /> {item.locked_by}</span>}</div>} onClick={() => void openDetail(item)}><Card.Meta title={item.filename} description={<Space direction="vertical" size={2}><Typography.Text>{item.label}</Typography.Text><Typography.Text type="secondary">{item.review_status === 'reviewed' ? `검수: ${item.reviewed_by ?? '-'}` : item.review_status}</Typography.Text></Space>} /></Card>)}</div> : <Empty />}
          <Pagination current={page} pageSize={48} total={images.data?.total ?? 0} showSizeChanger={false} onChange={(value) => { setPage(value); void closeDetail() }} />
        </section>
      </div>

      <Modal title="클래스 핫키 입력" open={hotkeyOpen} onCancel={() => { setHotkeyOpen(false); setHotkeyValue('') }} onOk={applyHotkey} okText="라벨 변경" cancelText="취소"><Input ref={hotkeyInput} value={hotkeyValue} onChange={(event) => setHotkeyValue(event.target.value.replace(/\D/g, ''))} onPressEnter={applyHotkey} placeholder="예: 1" inputMode="numeric" size="large" /><div className="hotkey-modal-list">{(hotkeys.data?.items ?? []).map((item) => <Tag key={item.key}>{item.key} · {item.label}</Tag>)}</div></Modal>
    </>
  )
}

function SummaryTable() {
  const { data } = useQuery({ queryKey: ['summary'], queryFn: fetchSummary, refetchInterval: 5000 })
  return <Card title="클래스별 데이터 분할 현황"><Table rowKey="label" dataSource={data?.classes ?? []} pagination={false} columns={[{ title: '불량 클래스', dataIndex: 'label' },{ title: '학습', dataIndex: 'train' },{ title: '검증', dataIndex: 'valid' },{ title: '시험', dataIndex: 'test' },{ title: '미지정', dataIndex: 'unassigned' },{ title: '합계', dataIndex: 'total' }]} /></Card>
}

function TrainSplitPanel({ worker }: { worker: string }) {
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [page, setPage] = useState(1)
  const [split, setSplit] = useState<SplitCode>()
  const images = useQuery({ queryKey: ['split-images', page, split], queryFn: () => fetchImages({ page, page_size: 50, split }), refetchInterval: 5000 })
  const auto = useMutation({ mutationFn: autoSplit, onSuccess: async (data) => { await qc.invalidateQueries(); message.success(`${data.updated}개 이미지를 자동 분할했습니다.`) } })
  const update = useMutation({ mutationFn: updateImage, onSuccess: async () => { await qc.invalidateQueries(); message.success('분할 정보를 변경했습니다.') }, onError: () => message.error('다른 작업자의 변경과 충돌했습니다.') })
  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <Card title="Train Split 자동 분할"><Form form={form} layout="vertical" initialValues={{ train_ratio: 80, valid_ratio: 10, test_ratio: 10, seed: 42, only_unassigned: true }} onFinish={(values) => auto.mutate(values)}><Row gutter={16}><Col span={6}><Form.Item name="train_ratio" label="학습 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col><Col span={6}><Form.Item name="valid_ratio" label="검증 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col><Col span={6}><Form.Item name="test_ratio" label="시험 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col><Col span={6}><Form.Item name="seed" label="랜덤 시드"><InputNumber /></Form.Item></Col></Row><Button type="primary" htmlType="submit" loading={auto.isPending}>자동 분할 실행</Button></Form></Card>
    <Card title="개별 분할 관리" extra={<Select allowClear placeholder="분할 필터" options={splitOptions} value={split} onChange={(value) => { setSplit(value); setPage(1) }} style={{ width: 150 }} />}><Table rowKey="image_id" dataSource={images.data?.items ?? []} pagination={false} columns={[{ title: '미리보기', dataIndex: 'image_url', width: 100, render: (url: string) => <img className="split-thumb" src={url} /> },{ title: '파일명', dataIndex: 'filename' },{ title: '클래스', dataIndex: 'label' },{ title: '최근 작업자', dataIndex: 'reviewed_by', width: 110 },{ title: '분할', dataIndex: 'split', width: 160, render: (value: SplitCode, row: ImageItem) => <Select value={value} options={splitOptions} style={{ width: 130 }} onChange={(next) => update.mutate({ image_id: row.image_id, actor: worker, expected_version: row.version, split: next })} /> }]} /><Pagination current={page} pageSize={50} total={images.data?.total ?? 0} showSizeChanger={false} onChange={setPage} /></Card>
  </Space>
}

function ExportPanel() {
  const [form] = Form.useForm()
  const mutation = useMutation({ mutationFn: exportDataset, onSuccess: (data) => message.success(`${data.version} 생성 완료 (${data.count}개)`) })
  return <Card title="데이터셋 내보내기"><Form form={form} layout="vertical" initialValues={{ dataset_name: 'aoi_dataset', mode: 'copy' }} onFinish={(values) => mutation.mutate(values)}><Form.Item name="dataset_name" label="데이터셋 이름"><Input /></Form.Item><Form.Item name="mode" label="파일 생성 방식"><Select options={[{ value: 'copy', label: '파일 복사' },{ value: 'hardlink', label: '하드링크 우선' },{ value: 'manifest', label: '목록 파일만 생성' }]} /></Form.Item><Button type="primary" htmlType="submit" loading={mutation.isPending}>내보내기 실행</Button></Form></Card>
}

export default function AppCollaborative() { return <AntApp><AppContent /></AntApp> }
