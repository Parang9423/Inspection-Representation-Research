import type { InputRef } from 'antd'
import {
  Alert, Button, Card, Checkbox, Empty, Form, Image, Input, Modal, Pagination,
  Popconfirm, Select, Space, Table, Tag, Typography,
} from 'antd'
import {
  ArrowLeftOutlined, CheckCircleOutlined, DeleteOutlined, FileSearchOutlined,
  HistoryOutlined, LeftOutlined, LockOutlined, RightOutlined, StopOutlined,
} from '@ant-design/icons'
import type { FolderItem, HotkeyItem, ImageItem, ReviewStatus } from './types'

const folderStatusMeta = {
  idle: { label: '미작업', color: 'default' },
  working: { label: '작업중', color: 'orange' },
  completed: { label: '완료', color: 'green' },
} as const

const reviewOptions = [
  { value: 'unreviewed', label: '미검수' },
  { value: 'reviewing', label: '작업중' },
  { value: 'reviewed', label: '완료' },
]

interface Props {
  worker: string
  folder: string
  folderInfo?: FolderItem
  images: ImageItem[]
  total: number
  page: number
  detail: ImageItem | null
  detailIndex: number
  hotkeys: HotkeyItem[]
  history: Array<Record<string, unknown>>
  search: string
  reviewFilter?: ReviewStatus
  mineOnly: boolean
  changedOnly: boolean
  hotkeyOpen: boolean
  hotkeyValue: string
  hotkeyInput: React.RefObject<InputRef | null>
  loading?: boolean
  onBack: () => void
  onSearch: (value: string) => void
  onReviewFilter: (value?: ReviewStatus) => void
  onMineOnly: (value: boolean) => void
  onChangedOnly: (value: boolean) => void
  onResetFilters: () => void
  onOpenLogs: () => void
  onCompleteFolder: () => void
  onReleaseFolder: (force: boolean) => void
  onOpenDetail: (item: ImageItem) => void
  onCloseDetail: () => void
  onMoveDetail: (offset: number) => void
  onApplyLabel: (label: string, moveNext: boolean) => void
  onDelete: () => void
  onPage: (page: number) => void
  onHotkeyOpen: (open: boolean) => void
  onHotkeyValue: (value: string) => void
  onApplyHotkey: () => void
}

export default function FolderReviewView(props: Props) {
  const {
    worker, folder, folderInfo, images, total, page, detail, detailIndex, hotkeys,
    history, reviewFilter, mineOnly, changedOnly, hotkeyOpen, hotkeyValue,
    hotkeyInput, loading, onBack, onSearch, onReviewFilter, onMineOnly,
    onChangedOnly, onResetFilters, onOpenLogs, onCompleteFolder, onReleaseFolder,
    onOpenDetail, onCloseDetail, onMoveDetail, onApplyLabel, onDelete, onPage,
    onHotkeyOpen, onHotkeyValue, onApplyHotkey,
  } = props
  const folderReadOnly = Boolean(folderInfo?.working_by && folderInfo.working_by !== worker)
  const status = folderInfo?.work_status ?? 'idle'

  return <>
    <Card className="toolbar folder-toolbar">
      <Space wrap>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>폴더 목록</Button>
        <Typography.Title level={4} style={{ margin: 0 }}>{folder}</Typography.Title>
        <Tag color={folderStatusMeta[status].color}>{folderStatusMeta[status].label}</Tag>
        {folderInfo?.working_by && <Tag color="orange">작업자 {folderInfo.working_by}</Tag>}
        <Tag color="blue">조회 {total}개</Tag>
        <Input.Search placeholder="파일명·현재 라벨 검색" allowClear onSearch={onSearch} style={{ width: 240 }} />
        <Select allowClear placeholder="검수 상태" options={reviewOptions} value={reviewFilter} onChange={onReviewFilter} style={{ width: 125 }} />
        <Checkbox checked={mineOnly} onChange={(event) => onMineOnly(event.target.checked)}>내 작업</Checkbox>
        <Checkbox checked={changedOnly} onChange={(event) => onChangedOnly(event.target.checked)}>라벨 변경됨</Checkbox>
        <Button icon={<FileSearchOutlined />} onClick={onResetFilters}>필터 초기화</Button>
        <Button icon={<HistoryOutlined />} onClick={onOpenLogs}>작업 로그</Button>
        {!folderReadOnly && <Button icon={<CheckCircleOutlined />} onClick={onCompleteFolder}>폴더 완료</Button>}
        {status === 'working' && <Button danger icon={<StopOutlined />} onClick={() => onReleaseFolder(folderReadOnly)}>작업 상태 해제</Button>}
      </Space>
    </Card>

    {folderReadOnly && <Alert
      type="warning"
      showIcon
      message={`${folderInfo?.working_by}님이 이 폴더를 작업 중입니다.`}
      description="이미지 조회는 가능하지만 다른 작업자가 잠근 이미지는 수정할 수 없습니다."
      style={{ marginBottom: 12 }}
    />}

    <div className={detail ? 'dataset-review detail-open' : 'dataset-review'}>
      {detail && <aside className="detail-pane">
        <div className="detail-header">
          <div><Typography.Title level={4}>클래스 검수</Typography.Title><Typography.Text type="secondary">{detail.filename}</Typography.Text></div>
          <Button onClick={onCloseDetail}>닫기</Button>
        </div>
        {detail.locked_by && detail.locked_by !== worker && <Alert type="warning" showIcon icon={<LockOutlined />} message={`${detail.locked_by}님이 검수 중입니다.`} style={{ marginBottom: 12 }} />}
        <div className="detail-image-wrap"><Image src={detail.image_url} preview /></div>
        <Space className="detail-navigation">
          <Button icon={<LeftOutlined />} disabled={detailIndex <= 0} onClick={() => onMoveDetail(-1)}>이전</Button>
          <Typography.Text>{detailIndex >= 0 ? detailIndex + 1 : '-'} / {images.length}</Typography.Text>
          <Button icon={<RightOutlined />} disabled={detailIndex < 0 || detailIndex >= images.length - 1} onClick={() => onMoveDetail(1)}>다음</Button>
        </Space>
        <Form layout="vertical"><Form.Item label="현재 클래스"><Select showSearch value={detail.label} disabled={Boolean(detail.locked_by && detail.locked_by !== worker)} options={hotkeys.map((item) => ({ value: item.label, label: `${item.key} · ${item.label}` }))} onChange={(label) => onApplyLabel(label, false)} /></Form.Item></Form>
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="blue">version {detail.version}</Tag>
          <Tag className={`status-tag status-${detail.review_status}`}>{detail.review_status}</Tag>
          {detail.reviewed_by && <Tag color="green">검수: {detail.reviewed_by}</Tag>}
          {detail.locked_by && <Tag color="orange">잠금: {detail.locked_by}</Tag>}
        </Space>
        <Card size="small" title="클래스 핫키" className="hotkey-card"><div className="hotkey-list">{hotkeys.map((item) => <Tag key={item.key} onClick={() => onApplyLabel(item.label, true)}>{item.key} · {item.label}</Tag>)}</div></Card>
        <Card size="small" title="변경 이력" className="history-card"><Table size="small" pagination={false} rowKey="history_id" dataSource={history} columns={[
          { title: '이전', dataIndex: 'previous_label', ellipsis: true },
          { title: '변경', dataIndex: 'new_label', ellipsis: true },
          { title: '작업자', dataIndex: 'changed_by', width: 90 },
          { title: '시간', dataIndex: 'changed_at', width: 150 },
        ]} /></Card>
        <Popconfirm title="이미지를 백업 폴더로 이동할까요?" okText="이동" cancelText="취소" disabled={Boolean(detail.locked_by && detail.locked_by !== worker)} onConfirm={onDelete}>
          <Button danger icon={<DeleteOutlined />} block disabled={Boolean(detail.locked_by && detail.locked_by !== worker)}>데이터 삭제(백업 이동)</Button>
        </Popconfirm>
      </aside>}

      <section className="grid-pane">
        {loading ? <Card loading /> : images.length ? <div className="image-grid">{images.map((item) => {
          const ownerClass = item.locked_by === worker ? 'mine' : item.locked_by ? 'locked' : ''
          return <Card
            key={item.image_id}
            hoverable
            className={`image-card review-${item.review_status} ${ownerClass} ${detail?.image_id === item.image_id ? 'selected' : ''}`}
            cover={<div className="thumb-wrap">
              <img loading="lazy" decoding="async" src={item.thumbnail_url ?? item.image_url} alt={item.filename} />
              <span className={`review-badge badge-${item.review_status}`}>{item.review_status === 'reviewed' ? '완료' : item.review_status === 'reviewing' ? '작업중' : '미검수'}</span>
              {item.locked_by && <span className="lock-badge"><LockOutlined /> {item.locked_by}</span>}
            </div>}
            onClick={() => onOpenDetail(item)}
          >
            <Card.Meta title={item.filename} description={<Space direction="vertical" size={2}>
              <Typography.Text>{item.label}</Typography.Text>
              <Typography.Text type="secondary">{item.review_status === 'reviewed' ? `검수: ${item.reviewed_by ?? '-'}` : item.locked_by ? `작업: ${item.locked_by}` : '미검수'}</Typography.Text>
            </Space>} />
          </Card>
        })}</div> : <Empty description="현재 필터에 해당하는 이미지가 없습니다." />}
        <Pagination current={page} pageSize={48} total={total} showSizeChanger={false} onChange={onPage} />
      </section>
    </div>

    <Modal title="클래스 핫키 입력" open={hotkeyOpen} onCancel={() => { onHotkeyOpen(false); onHotkeyValue('') }} onOk={onApplyHotkey} okText="라벨 변경" cancelText="취소">
      <Input ref={hotkeyInput} value={hotkeyValue} onChange={(event) => onHotkeyValue(event.target.value.replace(/\D/g, ''))} onPressEnter={onApplyHotkey} placeholder="예: 1" inputMode="numeric" size="large" />
      <div className="hotkey-modal-list">{hotkeys.map((item) => <Tag key={item.key}>{item.key} · {item.label}</Tag>)}</div>
    </Modal>
  </>
}
