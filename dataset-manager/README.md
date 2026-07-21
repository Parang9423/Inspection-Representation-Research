# AOI Dataset Manager

Streamlit PoC를 React + FastAPI 구조로 재구성한 내부망용 학습 데이터셋 관리 도구입니다.

## 구조

```text
dataset-manager/
├─ apps/
│  ├─ api/        # FastAPI + SQLite
│  └─ web/        # React + TypeScript + Ant Design
├─ data/
│  ├─ split_image/   # Git 제외
│  ├─ cam_image/     # Git 제외
│  ├─ database/      # Git 제외
│  └─ exports/       # Git 제외
└─ docker-compose.yml
```

## 주요 기능

- `data/split_image` 자동 스캔
- 폴더명을 초기 학습 라벨로 사용
- 이미지 그리드, 검색, 필터, 페이지네이션
- 다중 선택 및 라벨/학습·검증·시험/상태 일괄 변경
- 클래스별 분할 현황
- 클래스별 자동 분할
- 데이터셋 버전 내보내기
- CAM 기준 이미지 조회
- 내부망 다중 사용자 접근

## 보안 원칙

이 저장소는 Public이므로 실제 불량명, 고객사명, 제품명, 설비명 및 검사 이미지를 커밋하지 않습니다.
공개 코드와 샘플에서는 `D01`, `D02`와 같은 Taxonomy 코드를 사용하세요.

## 실행

### Docker Compose

```bash
cd dataset-manager
docker compose up --build
```

- React UI: `http://서버IP:5173`
- FastAPI: `http://서버IP:8000/docs`

### 로컬 실행

Backend:

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd apps/web
npm install
npm run dev -- --host 0.0.0.0
```

## 테스트

```bash
cd apps/api
pytest
```

```bash
cd apps/web
npm install
npm test
npm run build
```

## 현재 제한

- 1차 버전은 이미지 단위 Classification 데이터셋 관리가 중심입니다.
- Detection/Segmentation 좌표 및 Polygon 편집기는 후속 단계에서 추가합니다.
- CAM 차분 이미지는 Backend 후속 API로 확장 예정입니다.
- 운영 단계에서는 SQLite를 PostgreSQL로 전환하는 것을 권장합니다.
