import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import {
  App as AntApp,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Image,
  Input,
  Layout,
  Menu,
  Modal,
  Pagination,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'

const { Header, Sider, Content } = Layout
const { Title, Text } = Typography
const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const splitLabels: Record<string, string> = {
  unassigned: '미지정',
  train: '학습',
  valid: '검증',
  test: '시험',
}
const statusLabels: Record<string, string> = {
  included: '학습 포함',
  review: '검토 필요',
  excluded: '학습 제외',
}

type ImageItem = {
  image_id: string
  filename: string
  label: string
  source_label: string
  split: string
  status: string
  note: string
  size_bytes: number
  image_url: string
  cam_url: string
}

type ImageResponse = {
  items: ImageItem[]
  total: number
  page: number
  page_size: number
}

type SummaryResponse = {
  totals: { total: number; assigned: number; included: number; review: number }
  groups: Array<{ label: string; split: string; status: string; count: number }>
}

async function fetchImages(params: Record<string, unknown>): Promise<ImageResponse> {
  const { data } = await axios.get(`${API}/api/images`, { params })
  return data
}

async function fetchSummary(): Promise<SummaryResponse> {
  const { data } = await axios.get(`${API}/api/summary`)
  return data
}

function App() {
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(48)
  const [search, setSearch] = useState('')
  const [label, setLabel] = useState<string>()
  const [split, setSplit] = useState<string>()
  const [status, setStatus] = useState<string>()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [detail, setDetail] = useState<ImageItem | null>(null)
  const [batchOpen, setBatchOpen] = useState(false)
  const [autoSplitOpen, setAutoSplitOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [batchForm] = Form.useForm()
  const [splitForm] = Form.useForm()
  const [exportForm] = Form.useForm()

  const filters = { page, page_size: pageSize, search: search || undefined, label, split, status }
  const imagesQuery = useQuery({ queryKey: ['images', filters], queryFn: () => fetchImages(filters) })
  const summaryQuery = useQuery({ queryKey: ['summary'], queryFn: fetchSummary })

  const labels = useMemo(
    () => [...new Set(summaryQuery.data?.groups.map((item) => item.label) ?? [])].sort(),
    [summaryQuery.data],
  )

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['images'] }),
      queryClient.invalidateQueries({ queryKey: ['summary'] }),
    ])
  }

  const scanMutation = useMutation({
    mutationFn: () => axios.post(`${API}/api/scan`),
    onSuccess: async ({ data }) => {
      message.success(`${data.count.toLocaleString()}개 이미지를 동기화했습니다.`)
      await refresh()
    },
  })

  const batchMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      axios.patch(`${API}/api/images/batch`, { image_ids: selectedIds, ...values }),
    onSuccess: async ({ data }) => {
      message.success(`${data.updated}개 이미지를 변경했습니다.`)
      setSelectedIds([])
      setBatchOpen(false)
      batchForm.resetFields()
      await refresh()
    },
  })

  const autoSplitMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => axios.post(`${API}/api/splits/auto`, values),
    onSuccess: async ({ data }) => {
      message.success(`${data.updated}개 이미지의 분할을 지정했습니다.`)
      setAutoSplitOpen(false)
      await refresh()
    },
  })

  const exportMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) => axios.post(`${API}/api/exports`, values),
    onSuccess: ({ data }) => {
      message.success(`${data.count}개 이미지 내보내기 완료`)
      Modal.info({ title: '내보내기 완료', content: data.path })
      setExportOpen(false)
    },
  })

  const groupedRows = useMemo(() => {
    const map = new Map<string, Record<string, number | string>>()
    for (const row of summaryQuery.data?.groups ?? []) {
      const current = map.get(row.label) ?? {
        key: row.label,
        label: row.label,
        train: 0,
        valid: 0,
        test: 0,
        unassigned: 0,
        total: 0,
      }
      current[row.split] = Number(current[row.split] ?? 0) + row.count
      current.total = Number(current.total) + row.count
      map.set(row.label, current)
    }
    return [...map.values()]
  }, [summaryQuery.data])

  const columns: ColumnsType<Record<string, number | string>> = [
    { title: '불량 유형', dataIndex: 'label', fixed: 'left' },
    { title: '학습', dataIndex: 'train', width: 90 },
    { title: '검증', dataIndex: 'valid', width: 90 },
    { title: '시험', dataIndex: 'test', width: 90 },
    { title: '미지정', dataIndex: 'unassigned', width: 90 },
    { title: '합계', dataIndex: 'total', width: 90 },
  ]

  return (
    <Layout className="app-shell">
      <Sider width={248} className="side-panel">
        <div className="brand-block">
          <div className="brand-mark">AI</div>
          <div>
            <Text className="brand-title">AOI Dataset</Text>
            <Text className="brand-subtitle">Manager</Text>
          </div>
        </div>
        <Menu
          theme="dark"
          selectedKeys={['dataset']}
          items={[
            { key: 'dataset', label: '학습 데이터셋' },
            { key: 'summary', label: '클래스 현황' },
            { key: 'versions', label: '데이터셋 버전' },
          ]}
        />
        <div className="side-footer">
          <Button block onClick={() => scanMutation.mutate()} loading={scanMutation.isPending}>
            폴더 다시 스캔
          </Button>
        </div>
      </Sider>

      <Layout>
        <Header className="top-header">
          <div>
            <Title level={3} className="page-title">AOI 학습 데이터셋 관리자</Title>
            <Text type="secondary">원본 폴더를 유지하면서 라벨과 데이터 분할을 관리합니다.</Text>
          </div>
          <Space>
            <Button onClick={() => setAutoSplitOpen(true)}>자동 분할</Button>
            <Button type="primary" onClick={() => setExportOpen(true)}>데이터 내보내기</Button>
          </Space>
        </Header>

        <Content className="content-area">
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={12} xl={6}>
              <Card><Statistic title="전체 이미지" value={summaryQuery.data?.totals.total ?? 0} /></Card>
            </Col>
            <Col xs={24} sm={12} xl={6}>
              <Card><Statistic title="학습 포함" value={summaryQuery.data?.totals.included ?? 0} /></Card>
            </Col>
            <Col xs={24} sm={12} xl={6}>
              <Card><Statistic title="검토 필요" value={summaryQuery.data?.totals.review ?? 0} /></Card>
            </Col>
            <Col xs={24} sm={12} xl={6}>
              <Card>
                <Statistic title="분할 지정" value={summaryQuery.data?.totals.assigned ?? 0} />
                <Progress
                  percent={Math.round(((summaryQuery.data?.totals.assigned ?? 0) / Math.max(summaryQuery.data?.totals.total ?? 1, 1)) * 100)}
                  showInfo={false}
                  size="small"
                />
              </Card>
            </Col>
          </Row>

          <Card className="workspace-card">
            <Tabs
              items={[
                {
                  key: 'grid',
                  label: '이미지 그리드',
                  children: (
                    <>
                      <Flex gap={12} wrap="wrap" className="filter-row">
                        <Input.Search
                          allowClear
                          placeholder="파일명·경로·라벨 검색"
                          onSearch={(value) => { setSearch(value); setPage(1) }}
                          className="search-input"
                        />
                        <Select
                          allowClear
                          placeholder="불량 유형"
                          options={labels.map((item) => ({ label: item, value: item }))}
                          onChange={(value) => { setLabel(value); setPage(1) }}
                          className="filter-select"
                        />
                        <Select
                          allowClear
                          placeholder="데이터 분할"
                          options={Object.entries(splitLabels).map(([value, text]) => ({ value, label: text }))}
                          onChange={(value) => { setSplit(value); setPage(1) }}
                          className="filter-select"
                        />
                        <Select
                          allowClear
                          placeholder="관리 상태"
                          options={Object.entries(statusLabels).map(([value, text]) => ({ value, label: text }))}
                          onChange={(value) => { setStatus(value); setPage(1) }}
                          className="filter-select"
                        />
                        <Button
                          disabled={!selectedIds.length}
                          type="primary"
                          onClick={() => setBatchOpen(true)}
                        >
                          선택 {selectedIds.length}개 일괄 편집
                        </Button>
                      </Flex>

                      {imagesQuery.data?.items.length ? (
                        <div className="image-grid">
                          {imagesQuery.data.items.map((item) => {
                            const checked = selectedIds.includes(item.image_id)
                            return (
                              <Card
                                key={item.image_id}
                                className={`image-card ${checked ? 'selected' : ''}`}
                                cover={
                                  <div className="image-wrap" onClick={() => setDetail(item)}>
                                    <Image
                                      preview={false}
                                      src={`${API}${item.image_url}`}
                                      alt={item.filename}
                                      fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='320' height='220'%3E%3Crect width='100%25' height='100%25' fill='%23eef1f6'/%3E%3C/svg%3E"
                                    />
                                  </div>
                                }
                                actions={[
                                  <Checkbox
                                    checked={checked}
                                    onChange={(event) => {
                                      setSelectedIds((current) =>
                                        event.target.checked
                                          ? [...current, item.image_id]
                                          : current.filter((id) => id !== item.image_id),
                                      )
                                    }}
                                  >선택</Checkbox>,
                                  <Button type="link" onClick={() => setDetail(item)}>상세</Button>,
                                ]}
                              >
                                <Card.Meta
                                  title={<Text ellipsis={{ tooltip: item.filename }}>{item.filename}</Text>}
                                  description={
                                    <Space direction="vertical" size={4} className="card-meta">
                                      <Text>{item.label}</Text>
                                      <Space wrap>
                                        <Tag color={item.split === 'train' ? 'blue' : item.split === 'valid' ? 'gold' : item.split === 'test' ? 'purple' : 'default'}>
                                          {splitLabels[item.split]}
                                        </Tag>
                                        <Tag color={item.status === 'included' ? 'green' : item.status === 'review' ? 'orange' : 'red'}>
                                          {statusLabels[item.status]}
                                        </Tag>
                                      </Space>
                                    </Space>
                                  }
                                />
                              </Card>
                            )
                          })}
                        </div>
                      ) : <Empty description="조건에 맞는 이미지가 없습니다." />}

                      <Flex justify="end" className="pagination-row">
                        <Pagination
                          current={page}
                          pageSize={pageSize}
                          total={imagesQuery.data?.total ?? 0}
                          showSizeChanger
                          pageSizeOptions={[24, 48, 96, 192]}
                          showTotal={(total) => `총 ${total.toLocaleString()}개`}
                          onChange={(nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize) }}
                        />
                      </Flex>
                    </>
                  ),
                },
                {
                  key: 'summary',
                  label: '클래스 현황',
                  children: <Table columns={columns} dataSource={groupedRows} pagination={{ pageSize: 20 }} scroll={{ x: 720 }} />,
                },
              ]}
            />
          </Card>
        </Content>
      </Layout>

      <Drawer title="이미지 상세" width={620} open={Boolean(detail)} onClose={() => setDetail(null)}>
        {detail && (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Image src={`${API}${detail.image_url}`} width="100%" />
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="파일명">{detail.filename}</Descriptions.Item>
              <Descriptions.Item label="현재 라벨">{detail.label}</Descriptions.Item>
              <Descriptions.Item label="원본 폴더 라벨">{detail.source_label}</Descriptions.Item>
              <Descriptions.Item label="데이터 분할">{splitLabels[detail.split]}</Descriptions.Item>
              <Descriptions.Item label="관리 상태">{statusLabels[detail.status]}</Descriptions.Item>
              <Descriptions.Item label="메모">{detail.note || '-'}</Descriptions.Item>
            </Descriptions>
            <Card title="CAM 기준 이미지" size="small">
              <Image src={`${API}${detail.cam_url}`} fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='480' height='240'%3E%3Crect width='100%25' height='100%25' fill='%23f5f5f5'/%3E%3Ctext x='50%25' y='50%25' text-anchor='middle' fill='%23999'%3ECAM 이미지 없음%3C/text%3E%3C/svg%3E" />
            </Card>
          </Space>
        )}
      </Drawer>

      <Modal
        title="선택 이미지 일괄 편집"
        open={batchOpen}
        onCancel={() => setBatchOpen(false)}
        onOk={() => batchForm.submit()}
        okText="적용"
        cancelText="취소"
        confirmLoading={batchMutation.isPending}
      >
        <Form form={batchForm} layout="vertical" onFinish={(values) => batchMutation.mutate(values)}>
          <Form.Item name="label" label="불량 라벨">
            <Select allowClear options={labels.map((item) => ({ label: item, value: item }))} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="split" label="데이터 분할">
                <Select allowClear options={Object.entries(splitLabels).map(([value, text]) => ({ value, label: text }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="status" label="관리 상태">
                <Select allowClear options={Object.entries(statusLabels).map(([value, text]) => ({ value, label: text }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="메모"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="클래스별 자동 분할"
        open={autoSplitOpen}
        onCancel={() => setAutoSplitOpen(false)}
        onOk={() => splitForm.submit()}
        okText="분할 실행"
        cancelText="취소"
        confirmLoading={autoSplitMutation.isPending}
      >
        <Form
          form={splitForm}
          layout="vertical"
          initialValues={{ train_ratio: 80, valid_ratio: 10, test_ratio: 10, seed: 42, only_unassigned: true }}
          onFinish={(values) => autoSplitMutation.mutate(values)}
        >
          <Row gutter={12}>
            <Col span={8}><Form.Item name="train_ratio" label="학습 비율"><Input type="number" /></Form.Item></Col>
            <Col span={8}><Form.Item name="valid_ratio" label="검증 비율"><Input type="number" /></Form.Item></Col>
            <Col span={8}><Form.Item name="test_ratio" label="시험 비율"><Input type="number" /></Form.Item></Col>
          </Row>
          <Form.Item name="seed" label="랜덤 시드"><Input type="number" /></Form.Item>
          <Form.Item name="only_unassigned" valuePropName="checked"><Checkbox>미지정 이미지만 분할</Checkbox></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="데이터셋 내보내기"
        open={exportOpen}
        onCancel={() => setExportOpen(false)}
        onOk={() => exportForm.submit()}
        okText="내보내기"
        cancelText="취소"
        confirmLoading={exportMutation.isPending}
      >
        <Form
          form={exportForm}
          layout="vertical"
          initialValues={{ name: 'aoi_dataset', mode: 'copy' }}
          onFinish={(values) => exportMutation.mutate(values)}
        >
          <Form.Item name="name" label="데이터셋 이름" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="mode" label="파일 생성 방식">
            <Select options={[
              { value: 'copy', label: '파일 복사' },
              { value: 'hardlink', label: '하드링크 우선' },
              { value: 'manifest', label: '목록 파일만 생성' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default function RootApp() {
  return <AntApp><App /></AntApp>
}
