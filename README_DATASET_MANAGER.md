# AOI Dataset Manager — React/FastAPI PoC

기존 Streamlit PoC를 React + FastAPI로 재구성한 내부망용 데이터셋 관리 도구입니다.

## 주요 기능
- `data/split_image` 자동 스캔 및 폴더명 기반 초기 라벨 생성
- 이미지 카드 그리드, 검색, 분할/상태 필터
- 다중 선택 및 학습/검증/시험 분할 일괄 변경
- 학습 포함/검토 필요/학습 제외 관리
- 클래스별 분할 현황 및 자동 분할
- 버전별 내보내기와 `manifest.csv`, `dataset.yaml`, `statistics.json`
- CAM 기준 이미지 상세 조회

## 보안 원칙
이 저장소는 Public이므로 실제 불량명, 고객사명, 제품명, 설비명과 실제 이미지를 커밋하지 않습니다. 저장소에는 `D01`, `D02`와 같은 Taxonomy 코드만 사용하세요.

## 실행
```bash
docker compose up --build
```
같은 내부망 PC에서 `http://서버PC_IP:8501`로 접속합니다.

## 개발 실행
Backend: `cd apps/api && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
Frontend: `cd apps/web && npm install && npm run dev`

## 테스트
```bash
cd apps/api && pytest
cd apps/web && npm test && npm run build
```
