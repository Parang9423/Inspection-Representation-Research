import { Modal, Table } from 'antd'
import type { WorkLog } from './types'

const actionLabels: Record<string, string> = {
  start: '작업 시작',
  release: '작업 해제',
  force_release: '강제 해제',
  complete: '작업 완료',
  auto_release: '자동 해제',
  image_reviewed: '이미지 검수',
  label_change: '라벨 변경',
}

interface Props {
  open: boolean
  folder?: string | null
  items: WorkLog[]
  loading?: boolean
  onClose: () => void
}

export default function WorkLogModal({ open, folder, items, loading, onClose }: Props) {
  return <Modal
    title={folder ? `${folder} 작업 로그` : '전체 작업 로그'}
    open={open}
    width={920}
    footer={null}
    onCancel={onClose}
  >
    <Table
      rowKey="log_id"
      size="small"
      loading={loading}
      dataSource={items}
      pagination={{ pageSize: 20 }}
      columns={[
        { title: '폴더', dataIndex: 'folder_name', ellipsis: true },
        { title: '작업', dataIndex: 'action', width: 110, render: (value: string) => actionLabels[value] ?? value },
        { title: '작업자', dataIndex: 'actor', width: 110 },
        { title: '상세', dataIndex: 'detail', ellipsis: true },
        { title: '시간', dataIndex: 'created_at', width: 190 },
      ]}
    />
  </Modal>
}
