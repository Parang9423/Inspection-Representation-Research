# Legacy Streamlit PoC

React 전환 이전 Streamlit 기반 AOI Dataset Manager의 보존 위치입니다.

현재 브랜치에서는 신규 개발을 `apps/web`과 `apps/api`에서 진행합니다. Streamlit PoC의 기능 명세는 다음과 같습니다.

- `./split_image` 자동 스캔
- SQLite 기반 라벨 및 Split 관리
- 학습/검증/시험 자동 분할
- 데이터셋 Export
- CAM 이미지 조회
- 학습 Rule 관리

실제 이미지, SQLite DB, Export 결과는 공개 저장소에 커밋하지 않습니다.
기존 사내 실행본은 별도 폐쇄망 보관본을 기준으로 유지하고, 이후 필요한 기능만 React/FastAPI 구조로 이관합니다.
