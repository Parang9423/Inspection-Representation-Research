from . import main as main_module
from .collaboration import ensure_collaboration_schema, router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .dataset_browser import list_hotkeys, router as dataset_browser_router

app = main_module.app

# main.py의 기본 startup은 매번 전체 폴더를 스캔하므로 제거합니다.
# DB가 비어 있을 때만 최초 자동 스캔하고, 이후에는 기존 DB를 즉시 제공합니다.
if main_module.startup in app.router.on_startup:
    app.router.on_startup.remove(main_module.startup)

# 기존 핫키 API는 실제 파일 시스템을 매번 조회합니다. 폴더 우선 탐색 구조에서는
# DB에 저장된 전체 source_label을 기준으로 핫키를 만들어야 하므로 기존 경로를 교체합니다.
app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) != "/api/labels/hotkeys"
]


@app.get("/api/labels/hotkeys")
def cached_label_hotkeys() -> dict:
    return list_hotkeys()


app.include_router(collaboration_router)
app.include_router(collaboration_summary_router)
app.include_router(dataset_browser_router)


@app.on_event("startup")
def initialize_application() -> None:
    main_module.init_db()

    with main_module.connect() as conn:
        image_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    if image_count == 0:
        main_module.scan_images()

    ensure_collaboration_schema()
