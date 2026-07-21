import {
  Button, Card, Col, Empty, Popconfirm, Progress, Row, Space, Statistic, Tag,
  Typography,
} from 'antd'
import {
  FolderOpenOutlined, FolderOutlined, HistoryOutlined, ReloadOutlined,
  StopOutlined, SyncOutlined,
} from '@ant-design/icons'
import type { FolderItem, ScanStatus } from './types'

const folderStatusMeta = {
  idle: { label: '미작업', color: 'default' },
  working: { label: '작업중', color: 'orange' },
  completed: { label: '완료', color: 'green' },
} as const

interface Props {
  folders: FolderItem[]
  scanStatus?: ScanStatus
  scanPending: boolean
  onScan: (mode: 'quick' | 'full') => void
  onOpenFolder: (folder: FolderItem) => void
  onOpenLogs: (folder?: string) => void
  onForceRelease: (folder: FolderItem) => void
}

export default function DatasetDashboard({
  folders, scanStatus, scanPending, onScan, onOpenFolder, onOpenLogs, onForceRelease,
}: Props) {
  const totals = folders.reduce((acc, folder) => {
    acc.images += folder.image_count
    acc.reviewed += folder.reviewed_count
    if (folder.work_status === 'working') acc.working += 1
    return acc
  }, { images: 0, reviewed: 0, working: 0 })

  const scanRunning = Boolean(scanStatus?.running)
  const scanLabel = scanRunning
    ? `${scanStatus?.current_folder ?? '폴더 탐색 중'} · 처리 ${scanStatus?.processed ?? 0} · 신규 ${scanStatus?.added ?? 0}`
    : scanStatus?.status === 'failed'
      ? `최근 스캔 실패: ${scanStatus.error ?? '원인 미확인'}`
      : '빠른 증분 스캔은 DB에 없는 신규 이미지만 추가하고, 실패 시 체크포인트에서 재개합니다.'

  return <Space direction="vertical" size={16} style={{ width: '100%' }}>
    <Row gutter={[16, 16]} className="stats-row">
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="원본 폴더" value={folders.length} suffix="개" /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="전체 이미지" value={totals.images} suffix="장" /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="검수 완료" value={totals.reviewed} suffix="장" /></Card></Col>
      <Col xs={24} sm={12} xl={6}><Card><Statistic title="작업 중 폴더" value={totals.working} suffix="개" /></Card></Col>
    </Row>

    <Card className="dataset-command-bar">
      <Space wrap size="middle">
        <Button type="primary" icon={<SyncOutlined />} loading={scanPending || scanRunning} onClick={() => onScan('quick')}>
          빠른 증분 스캔
        </Button>
        <Popconfirm title="전체 파일의 변경 및 삭제 여부까지 다시 확인합니다." okText="실행" cancelText="취소" onConfirm={() => onScan('full')}>
          <Button icon={<ReloadOutlined />} disabled={scanRunning}>전체 재스캔</Button>
        </Popconfirm>
        <Button icon={<HistoryOutlined />} onClick={() => onOpenLogs()}>전체 작업 로그</Button>
        <Typography.Text type={scanStatus?.status === 'failed' ? 'danger' : 'secondary'}>{scanLabel}</Typography.Text>
      </Space>
      {scanRunning && <Progress percent={scanStatus?.processed ? undefined : 0} status="active" showInfo={false} style={{ marginTop: 12 }} />}
    </Card>

    <div className="dataset-section-heading">
      <div>
        <Typography.Title level={4}>폴더 작업 현황</Typography.Title>
        <Typography.Text type="secondary">폴더를 선택하면 해당 폴더의 이미지만 페이지 단위로 불러옵니다.</Typography.Text>
      </div>
    </div>

    {folders.length ? <div className="folder-grid">
      {folders.map((folder) => {
        const meta = folderStatusMeta[folder.work_status]
        return <Card key={folder.folder_name} hoverable className={`folder-card folder-${folder.work_status}`} onClick={() => onOpenFolder(folder)}>
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
          <Typography.Text type="secondary">
            {folder.working_by ? `작업자: ${folder.working_by}` : '현재 작업자 없음'}
          </Typography.Text>
          <Progress percent={Math.round(folder.progress)} size="small" status={folder.work_status === 'completed' ? 'success' : 'active'} />
          <Space className="folder-card-actions" onClick={(event) => event.stopPropagation()}>
            <Button type="link" icon={<FolderOpenOutlined />} onClick={() => onOpenFolder(folder)}>열기</Button>
            <Button type="link" icon={<HistoryOutlined />} onClick={() => onOpenLogs(folder.folder_name)}>로그</Button>
            {folder.work_status === 'working' && <Popconfirm title={`${folder.working_by ?? '현재 작업자'}의 작업 상태를 강제로 해제할까요?`} okText="해제" cancelText="취소" onConfirm={() => onForceRelease(folder)}>
              <Button type="link" danger icon={<StopOutlined />}>강제 해제</Button>
            </Popconfirm>}
          </Space>
        </Card>
      })}
    </div> : <Empty description="인식된 폴더가 없습니다. 빠른 증분 스캔을 실행해 주세요." />}
  </Space>
}
