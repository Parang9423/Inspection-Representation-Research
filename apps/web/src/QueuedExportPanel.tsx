import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Progress, Select, Space, Typography, message } from 'antd'
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

interface ExportTask {
  task_id?: string
  status: 'idle' | 'queued' | 'running' | 'finished' | 'failed'
  result?: { version: string; path: string; count: number } | null
  error?: string | null
}

async function queueExport(payload: { dataset_name: string; mode: 'copy' | 'hardlink' | 'manifest'; actor?: string }) {
  return (await api.post<ExportTask>('/exports', payload)).data
}

async function fetchExportTask(taskId: string) {
  return (await api.get<ExportTask>(`/exports/tasks/${taskId}`)).data
}

export default function QueuedExportPanel({ worker }: { worker: string }) {
  const [form] = Form.useForm()
  const [taskId, setTaskId] = useState<string | null>(null)
  const mutation = useMutation({
    mutationFn: queueExport,
    onSuccess: (task) => {
      if (task.task_id) setTaskId(task.task_id)
      message.info('내보내기 작업을 백그라운드 큐에 등록했습니다.')
    },
    onError: () => message.error('내보내기 작업 등록에 실패했습니다.'),
  })
  const task = useQuery({
    queryKey: ['export-task', taskId],
    queryFn: () => fetchExportTask(taskId!),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1000 : false
    },
  })

  useEffect(() => {
    if (task.data?.status === 'finished' && task.data.result) {
      message.success(`${task.data.result.version} 생성 완료 (${task.data.result.count}개)`)
    }
  }, [task.data?.status])

  const status = task.data

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {status?.status === 'queued' && (
        <Alert type="info" showIcon message="내보내기 대기 중" description="앞선 스캔 또는 내보내기 작업이 끝나면 자동으로 시작됩니다." />
      )}
      {status?.status === 'running' && (
        <Alert
          type="info"
          showIcon
          message="데이터셋 내보내기 실행 중"
          description={<Progress percent={100} status="active" showInfo={false} />}
        />
      )}
      {status?.status === 'finished' && status.result && (
        <Alert
          type="success"
          showIcon
          message={`${status.result.version} 생성 완료`}
          description={`이미지 ${status.result.count.toLocaleString()}개 · ${status.result.path}`}
        />
      )}
      {status?.status === 'failed' && (
        <Alert type="error" showIcon message="내보내기 실패" description={status.error ?? 'API 로그를 확인하세요.'} />
      )}

      <Card title="데이터셋 내보내기">
        <Form
          form={form}
          layout="vertical"
          initialValues={{ dataset_name: 'aoi_dataset', mode: 'copy' }}
          onFinish={(values) => mutation.mutate({ ...values, actor: worker })}
        >
          <Form.Item name="dataset_name" label="데이터셋 이름" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="mode" label="파일 생성 방식">
            <Select options={[
              { value: 'copy', label: '파일 복사' },
              { value: 'hardlink', label: '하드링크 우선' },
              { value: 'manifest', label: '목록 파일만 생성' },
            ]} />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={mutation.isPending}
            disabled={status?.status === 'queued' || status?.status === 'running'}
          >
            내보내기 작업 등록
          </Button>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            스캔과 내보내기는 동일한 백그라운드 워커에서 순차 실행됩니다.
          </Typography.Paragraph>
        </Form>
      </Card>
    </Space>
  )
}
