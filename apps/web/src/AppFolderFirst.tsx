import { useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App as AntApp,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Layout,
  Menu,
  Modal,
  Pagination,
  Row,
  Select,
  Space,
  Table,
  Typography,
  message,
} from 'antd'
import {
  DatabaseOutlined,
  ExportOutlined,
  SplitCellsOutlined,
  UserOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import FolderDatasetGrid from './FolderDatasetGrid'
import './collaborative.css'

const { Header, Sider, Content } = Layout
const api = axios.create({ baseURL: '/api' })
const WORKER_KEY = 'aoi-dataset-worker'

type SplitCode = 'unassigned' | 'train' | 'valid' | 'test'

interface ImageItem {
  image_id: string
  filename: string
  label: string
  split: SplitCode
  image_url: string
  version: number
  reviewed_by?: string | null
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

async function fetchSummary() {
  return (await api.get<Summary>('/summary')).data
}

async function updateImage(payload: { image_id: string; actor: string; expected_version: number; split: SplitCode }) {
  return (await api.patch('/collaboration/images/update', payload)).data
}

async function autoSplit(payload: { train_ratio: number; valid_ratio: number; test_ratio: number; seed: number; only_unassigned: boolean }) {
  return (await api.post('/splits/auto', payload)).data
}

async function exportDataset(payload: { dataset_name: string; mode: 'copy' | 'hardlink' | 'manifest' }) {
  return (await api.post('/exports', payload)).data
}

function SummaryTable() {
  const { data } = useQuery({ queryKey: ['summary'], queryFn: fetchSummary, refetchInterval: 5000 })
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

function TrainSplitPanel({ worker }: { worker: string }) {
  const qc = useQueryClient()
  const [form] = Form.useForm()
  const [page, setPage] = useState(1)
  const [split, setSplit] = useState<SplitCode>()
  const images = useQuery({
    queryKey: ['split-images', page, split],
    queryFn: () => fetchImages({ page, page_size: 50, split }),
    refetchInterval: 5000,
  })
  const auto = useMutation({
    mutationFn: autoSplit,
    onSuccess: async (data) => {
      await qc.invalidateQueries()
      message.success(`${data.updated}개 이미지를 자동 분할했습니다.`)
    },
  })
  const update = useMutation({
    mutationFn: updateImage,
    onSuccess: async () => {
      await qc.invalidateQueries()
      message.success('분할 정보를 변경했습니다.')
    },
    onError: () => message.error('다른 작업자의 변경과 충돌했습니다.'),
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
        extra={(
          <Select
            allowClear
            placeholder="분할 필터"
            options={splitOptions}
            value={split}
            onChange={(value) => { setSplit(value); setPage(1) }}
            style={{ width: 150 }}
          />
        )}
      >
        <Table
          rowKey="image_id"
          dataSource={images.data?.items ?? []}
          pagination={false}
          columns={[
            { title: '미리보기', dataIndex: 'image_url', width: 100, render: (url: string) => <img className="split-thumb" src={url} /> },
            { title: '파일명', dataIndex: 'filename' },
            { title: '클래스', dataIndex: 'label' },
            { title: '최근 작업자', dataIndex: 'reviewed_by', width: 110 },
            {
              title: '분할',
              dataIndex: 'split',
              width: 160,
              render: (value: SplitCode, row: ImageItem) => (
                <Select
                  value={value}
                  options={splitOptions}
                  style={{ width: 130 }}
                  onChange={(next) => update.mutate({ image_id: row.image_id, actor: worker, expected_version: row.version, split: next })}
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
      <Form
        form={form}
        layout="vertical"
        initialValues={{ dataset_name: 'aoi_dataset', mode: 'copy' }}
        onFinish={(values) => mutation.mutate(values)}
      >
        <Form.Item name="dataset_name" label="데이터셋 이름"><Input /></Form.Item>
        <Form.Item name="mode" label="파일 생성 방식">
          <Select options={[
            { value: 'copy', label: '파일 복사' },
            { value: 'hardlink', label: '하드링크 우선' },
            { value: 'manifest', label: '목록 파일만 생성' },
          ]} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={mutation.isPending}>내보내기 실행</Button>
      </Form>
    </Card>
  )
}

function AppContent() {
  const [menu, setMenu] = useState('dataset')
  const [worker, setWorker] = useState(localStorage.getItem(WORKER_KEY) ?? '')
  const [workerDraft, setWorkerDraft] = useState(worker)
  const [workerOpen, setWorkerOpen] = useState(!worker)

  const saveWorker = () => {
    const value = workerDraft.trim()
    if (!value) {
      message.error('작업자 이름을 입력하세요.')
      return
    }
    localStorage.setItem(WORKER_KEY, value)
    setWorker(value)
    setWorkerOpen(false)
  }

  const content: Record<string, ReactNode> = {
    dataset: <FolderDatasetGrid worker={worker} />,
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
              <Typography.Text type="secondary">폴더 기반 탐색 · 동시 검수 · 충돌 방지</Typography.Text>
            </div>
            <Button icon={<UserOutlined />} onClick={() => setWorkerOpen(true)}>작업자: {worker || '미설정'}</Button>
          </Header>
          <Content className="content">{worker ? content[menu] : <Empty description="작업자를 설정하세요." />}</Content>
        </Layout>
      </Layout>
      <Modal
        title="작업자 설정"
        open={workerOpen}
        closable={!!worker}
        maskClosable={false}
        onCancel={() => worker && setWorkerOpen(false)}
        onOk={saveWorker}
        okText="적용"
      >
        <Input
          value={workerDraft}
          onChange={(event) => setWorkerDraft(event.target.value)}
          onPressEnter={saveWorker}
          placeholder="예: 조동일"
          prefix={<UserOutlined />}
          autoFocus
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          작업자 이름은 이미지 잠금과 변경 이력에 저장됩니다.
        </Typography.Paragraph>
      </Modal>
    </>
  )
}

export default function AppFolderFirst() {
  return <AntApp><AppContent /></AntApp>
}
