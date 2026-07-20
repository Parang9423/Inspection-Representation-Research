import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Progress, Space, Tag, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

interface ScanStatus {
  status: 'idle' | 'discovering' | 'running' | 'finished' | 'failed'
  phase: string
  running: boolean
  current_folder?: string | null
  discovered: number
  processed: number
  total: number
  percent: number
  added: number
  updated: number
  unchanged: number
  deactivated: number
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
}

async function fetchScanStatus() {
  return (await api.get<ScanStatus>('/scan/status')).data
}

async function startScan() {
  return (await api.post<ScanStatus>('/scan/start')).data
}

export default function ScanStatusBanner() {
  const queryClient = useQueryClient()
  const scan = useQuery({
    queryKey: ['scan-status'],
    queryFn: fetchScanStatus,
    refetchInterval: (query) => query.state.data?.running ? 1000 : 5000,
  })
  const start = useMutation({
    mutationFn: startScan,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['scan-status'] })
      message.info('폴더 동기화를 백그라운드에서 시작했습니다.')
    },
    onError: () => message.error('폴더 동기화를 시작하지 못했습니다.'),
  })

  const status = scan.data
  if (!status || status.status === 'idle') return null

  if (status.status === 'failed') {
    return (
      <Alert
        className="scan-status-banner"
        type="error"
        showIcon
        message="데이터셋 인덱싱 실패"
        description={status.error ?? 'API 로그를 확인하세요.'}
        action={<Button icon={<ReloadOutlined />} loading={start.isPending} onClick={() => start.mutate()}>다시 시도</Button>}
      />
    )
  }

  if (status.running) {
    const discovering = status.status === 'discovering'
    return (
      <Alert
        className="scan-status-banner"
        type="info"
        showIcon
        message={discovering ? '이미지 파일을 탐색하고 있습니다.' : '데이터셋 DB를 구성하고 있습니다.'}
        description={(
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space wrap>
              {status.current_folder && <Tag color="blue">현재 폴더: {status.current_folder}</Tag>}
              <Typography.Text>
                {discovering
                  ? `${status.discovered.toLocaleString()}개 파일 발견`
                  : `${status.processed.toLocaleString()} / ${status.total.toLocaleString()}개 처리`}
              </Typography.Text>
            </Space>
            <Progress
              percent={discovering ? undefined : status.percent}
              status="active"
              showInfo={!discovering}
            />
            {!discovering && (
              <Typography.Text type="secondary">
                신규 {status.added.toLocaleString()} · 변경 {status.updated.toLocaleString()} · 기존 {status.unchanged.toLocaleString()}
              </Typography.Text>
            )}
          </Space>
        )}
      />
    )
  }

  return (
    <Alert
      className="scan-status-banner"
      type="success"
      showIcon
      closable
      message="데이터셋 동기화 완료"
      description={`전체 ${status.total.toLocaleString()}개 · 신규 ${status.added.toLocaleString()}개 · 변경 ${status.updated.toLocaleString()}개 · 비활성 ${status.deactivated.toLocaleString()}개`}
      action={<Button size="small" icon={<ReloadOutlined />} loading={start.isPending} onClick={() => start.mutate()}>다시 스캔</Button>}
    />
  )
}
