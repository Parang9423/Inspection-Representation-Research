import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
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
  ReloadOutlined,
  RightOutlined,
  SplitCellsOutlined,
} from '@ant-design/icons'
import {
  autoSplit,
  backupDelete,
  bulkUpdate,
  exportDataset,
  fetchHotkeys,
  fetchImages,
  fetchSummary,
  scanDataset,
} from './api/client'
import type { ImageItem, SplitCode } from './types'
import './styles.css'

const { Header, Sider, Content } = Layout
const splitOptions = [
  { value: 'unassigned', label: '미지정' },
  { value: 'train', label: '학습' },
  { value: 'valid', label: '검증' },
  { value: 'test', label: '시험' },
]
const splitLabel: Record<SplitCode, string> = {
  unassigned: '미지정',
  train: '학습',
  valid: '검증',
  test: '시험',
}

function DatasetGrid() {
  const qc = useQueryClient()
  const hotkeyInput = useRef<HTMLInputElement>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [hotkeyOpen, setHotkeyOpen] = useState(false)
  const [hotkeyValue, setHotkeyValue] = useState('')

  const images = useQuery({
    queryKey: ['images', page, search],
    queryFn: () => fetchImages({ page, page_size: 48, search: search || undefined }),
  })
  const summary = useQuery({ queryKey: ['summary'], queryFn: fetchSummary })
  const hotkeys = useQuery({ queryKey: ['hotkeys'], queryFn: fetchHotkeys })

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ['images'] })
    await qc.invalidateQueries({ queryKey: ['summary'] })
    await qc.invalidateQueries({ queryKey: ['hotkeys'] })
  }

  const update = useMutation({
    mutationFn: bulkUpdate,
    onSuccess: async (_, variables) => {
      if (detail && variables.image_ids.includes(detail.image_id) && variables.label) {
        setDetail({ ...detail, label: variables.label })
      }
      await refresh()
      message.success('라벨을 변경했습니다.')
    },
  })
  const remove = useMutation({
    mutationFn: backupDelete,
    onSuccess: async (data) => {
      setDetail(null)
      await refresh()
      message.success(`${data.moved}개 이미지를 백업 폴더로 이동했습니다.`)
    },
  })
  const scan = useMutation({
    mutationFn: scanDataset,
    onSuccess: async (data) => {
      await refresh()
      message.success(`${data.count}개 이미지를 동기화했습니다.`)
    },
  })

  const items = images.data?.items ?? []
  const detailIndex = detail ? items.findIndex((item) => item.image_id === detail.image_id) : -1
  const hotkeyMap = useMemo(
    () => new Map((hotkeys.data?.items ?? []).map((item) => [item.key, item.label])),
    [hotkeys.data],
  )

  const moveDetail = (offset: number) => {
    if (detailIndex < 0) return
    const next = items[detailIndex + offset]
    if (next) setDetail(next)
  }

  const applyHotkey = () => {
    if (!detail) return
    const label = hotkeyMap.get(hotkeyValue.trim())
    if (!label) {
      message.error('등록되지 않은 핫키 번호입니다.')
      return
    }
    update.mutate({ image_ids: [detail.image_id], label })
    setHotkeyOpen(false)
    setHotkeyValue('')
  }

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA') return
      if (event.key === 'Enter' && detail) {
        event.preventDefault()
        setHotkeyOpen(true)
      }
      if (event.key === 'ArrowLeft' && detail) moveDetail(-1)
      if (event.key === 'ArrowRight' && detail) moveDetail(1)
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  })

  useEffect(() => {
    if (hotkeyOpen) setTimeout(() => hotkeyInput.current?.focus(), 50)
  }, [hotkeyOpen])

  return (
    <>
      <Row gutter={16} className="stats-row">
        {[
          ['전체 이미지', 'total'],
          ['현재 클래스 수', 'classes'],
        ].map(([title, key]) => (
          <Col flex="1" key={key}>
            <Card>
              <Statistic
                title={title}
                value={key === 'classes' ? summary.data?.classes.length ?? 0 : summary.data?.totals.total ?? 0}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Card className="toolbar">
        <Space wrap>
          <Input.Search
            placeholder="파일명·라벨 검색"
            allowClear
            onSearch={(value) => {
              setSearch(value)
              setPage(1)
              setDetail(null)
            }}
            style={{ width: 300 }}
          />
          <Button icon={<ReloadOutlined />} loading={scan.isPending} onClick={() => scan.mutate()}>
            폴더 다시 스캔
          </Button>
          <Typography.Text type="secondary">
            이미지 선택 후 Enter → 번호 입력 → Enter로 라벨 변경
          </Typography.Text>
        </Space>
      </Card>

      <div className={detail ? 'dataset-review detail-open' : 'dataset-review'}>
        <section className="grid-pane">
          {items.length ? (
            <div className="image-grid">
              {items.map((item) => (
                <Card
                  key={item.image_id}
                  hoverable
                  className={detail?.image_id === item.image_id ? 'image-card selected' : 'image-card'}
                  cover={
                    <div className="thumb-wrap" onClick={() => setDetail(item)}>
                      <img src={item.image_url} alt={item.filename} />
                    </div>
                  }
                  onClick={() => setDetail(item)}
                >
                  <Card.Meta
                    title={item.filename}
                    description={
                      <Space direction="vertical" size={2}>
                        <Typography.Text>{item.label}</Typography.Text>
                      </Space>
                    }
                  />
                </Card>
              ))}
            </div>
          ) : (
            <Empty />
          )}
          <Pagination
            current={page}
            pageSize={48}
            total={images.data?.total ?? 0}
            showSizeChanger={false}
            onChange={(value) => {
              setPage(value)
              setDetail(null)
            }}
          />
        </section>

        {detail && (
          <aside className="detail-pane">
            <div className="detail-header">
              <div>
                <Typography.Title level={4}>클래스 검수</Typography.Title>
                <Typography.Text type="secondary">{detail.filename}</Typography.Text>
              </div>
              <Button onClick={() => setDetail(null)}>닫기</Button>
            </div>

            <div className="detail-image-wrap">
              <Image src={detail.image_url} preview />
            </div>

            <Space className="detail-navigation">
              <Button icon={<LeftOutlined />} disabled={detailIndex <= 0} onClick={() => moveDetail(-1)}>
                이전
              </Button>
              <Typography.Text>{detailIndex + 1} / {items.length}</Typography.Text>
              <Button icon={<RightOutlined />} disabled={detailIndex < 0 || detailIndex >= items.length - 1} onClick={() => moveDetail(1)}>
                다음
              </Button>
            </Space>

            <Form layout="vertical">
              <Form.Item label="현재 클래스">
                <Select
                  showSearch
                  value={detail.label}
                  options={(hotkeys.data?.items ?? []).map((item) => ({ value: item.label, label: `${item.key} · ${item.label}` }))}
                  onChange={(label) => update.mutate({ image_ids: [detail.image_id], label })}
                />
              </Form.Item>
            </Form>

            <Card size="small" title="클래스 핫키" className="hotkey-card">
              <div className="hotkey-list">
                {(hotkeys.data?.items ?? []).map((item) => (
                  <Tag key={item.key} onClick={() => update.mutate({ image_ids: [detail.image_id], label: item.label })}>
                    {item.key} · {item.label}
                  </Tag>
                ))}
              </div>
            </Card>

            <Popconfirm
              title="이미지를 백업 폴더로 이동할까요?"
              description="DB에서 제거되고 원본 파일은 backup_image의 동일 클래스 경로로 이동합니다."
              okText="이동"
              cancelText="취소"
              onConfirm={() => remove.mutate({ image_ids: [detail.image_id] })}
            >
              <Button danger icon={<DeleteOutlined />} block loading={remove.isPending}>
                데이터 삭제(백업 이동)
              </Button>
            </Popconfirm>
          </aside>
        )}
      </div>

      <Modal
        title="클래스 핫키 입력"
        open={hotkeyOpen}
        onCancel={() => {
          setHotkeyOpen(false)
          setHotkeyValue('')
        }}
        onOk={applyHotkey}
        okText="라벨 변경"
        cancelText="취소"
      >
        <Input
          ref={hotkeyInput}
          value={hotkeyValue}
          onChange={(event) => setHotkeyValue(event.target.value.replace(/\D/g, ''))}
          onPressEnter={applyHotkey}
          placeholder="예: 1"
          inputMode="numeric"
          size="large"
        />
        <div className="hotkey-modal-list">
          {(hotkeys.data?.items ?? []).map((item) => (
            <Tag key={item.key}>{item.key} · {item.label}</Tag>
          ))}
        </div>
      </Modal>
    </>
  )
}

function SummaryTable() {
  const { data } = useQuery({ queryKey: ['summary'], queryFn: fetchSummary })
  return (
    <Card title="클래스별 데이터 분할 현황">
      <Table
        rowKey="label"
        dataSource={data?.classes ?? []}
        pagination={false}
        columns={[
          { title: '불량 클래스', dataIndex: 'label' },
          { title: '학습', dataIndex: 'train' },
          { title: '검증', dataIndex: 'valid' },
          { title: '시험', dataIndex: 'test' },
          { title: '미지정', dataIndex: 'unassigned' },
          { title: '합계', dataIndex: 'total' },
        ]}
      />
    </Card>
  )
}

function TrainSplitPanel() {
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [page, setPage] = useState(1)
  const [split, setSplit] = useState<SplitCode>()
  const images = useQuery({
    queryKey: ['split-images', page, split],
    queryFn: () => fetchImages({ page, page_size: 50, split }),
  })
  const auto = useMutation({
    mutationFn: autoSplit,
    onSuccess: async (data) => {
      await qc.invalidateQueries()
      message.success(`${data.updated}개 이미지를 자동 분할했습니다.`)
    },
  })
  const update = useMutation({
    mutationFn: bulkUpdate,
    onSuccess: async () => {
      await qc.invalidateQueries()
      message.success('분할 정보를 변경했습니다.')
    },
  })

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="Train Split 자동 분할">
        <Form
          form={form}
          layout="vertical"
          initialValues={{ train_ratio: 80, valid_ratio: 10, test_ratio: 10, seed: 42, only_unassigned: true }}
          onFinish={(values) => auto.mutate(values)}
        >
          <Row gutter={16}>
            <Col span={6}><Form.Item name="train_ratio" label="학습 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col>
            <Col span={6}><Form.Item name="valid_ratio" label="검증 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col>
            <Col span={6}><Form.Item name="test_ratio" label="시험 비율"><InputNumber min={0} max={100} addonAfter="%" /></Form.Item></Col>
            <Col span={6}><Form.Item name="seed" label="랜덤 시드"><InputNumber /></Form.Item></Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={auto.isPending}>자동 분할 실행</Button>
        </Form>
      </Card>

      <Card
        title="개별 분할 관리"
        extra={<Select allowClear placeholder="분할 필터" options={splitOptions} value={split} onChange={(value) => { setSplit(value); setPage(1) }} style={{ width: 150 }} />}
      >
        <Table
          rowKey="image_id"
          dataSource={images.data?.items ?? []}
          pagination={false}
          columns={[
            { title: '미리보기', dataIndex: 'image_url', width: 100, render: (url: string) => <img className="split-thumb" src={url} /> },
            { title: '파일명', dataIndex: 'filename' },
            { title: '클래스', dataIndex: 'label' },
            {
              title: '분할',
              dataIndex: 'split',
              width: 160,
              render: (value: SplitCode, row: ImageItem) => (
                <Select
                  value={value}
                  options={splitOptions}
                  style={{ width: 130 }}
                  onChange={(next) => update.mutate({ image_ids: [row.image_id], split: next })}
                />
              ),
            },
          ]}
        />
        <Pagination current={page} pageSize={50} total={images.data?.total ?? 0} showSizeChanger={false} onChange={setPage} />
      </Card>
    </Space>
  )
}

function ExportPanel() {
  const [form] = Form.useForm()
  const mutation = useMutation({
    mutationFn: exportDataset,
    onSuccess: (data) => message.success(`${data.version} 생성 완료 (${data.count}개)`),
  })
  return (
    <Card title="데이터셋 내보내기">
      <Form form={form} layout="vertical" initialValues={{ dataset_name: 'aoi_dataset', mode: 'copy' }} onFinish={(values) => mutation.mutate(values)}>
        <Form.Item name="dataset_name" label="데이터셋 이름"><Input /></Form.Item>
        <Form.Item name="mode" label="파일 생성 방식">
          <Select options={[{ value: 'copy', label: '파일 복사' }, { value: 'hardlink', label: '하드링크 우선' }, { value: 'manifest', label: '목록 파일만 생성' }]} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={mutation.isPending}>내보내기 실행</Button>
      </Form>
    </Card>
  )
}

function AppContent() {
  const [menu, setMenu] = useState('dataset')
  const content: Record<string, ReactNode> = {
    dataset: <DatasetGrid />,
    summary: <SummaryTable />,
    split: <TrainSplitPanel />,
    export: <ExportPanel />,
  }
  return (
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
        <Header className="header">
          <Typography.Title level={3}>AOI 학습 데이터셋 관리자</Typography.Title>
          <Typography.Text type="secondary">클래스 검수 · Train Split · 백업 기반 삭제</Typography.Text>
        </Header>
        <Content className="content">{content[menu]}</Content>
      </Layout>
    </Layout>
  )
}

export default function App() {
  return <AntApp><AppContent /></AntApp>
}
