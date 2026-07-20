from . import main as main_module
from .collaboration import ensure_collaboration_schema, router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .dataset_browser import list_hotkeys, router as dataset_browser_router

app = main_module.app

# main.py의 기본 startup은 매번 전체 폴더를 스캔하므로 제거합니다.
# DB가 비어 있을 때만 최초 자동 스캔하고, 이후에는 기존 DB를 즉시 제공합니다.
if main_module.startup in app.router.on_startup:
    app.router.on_startup.remove(main_module.startup)

# 기존 /api/labels/hotkeys 라우트는 main.py의 label_hotkeys()를 호출합니다.
# 라우트 자체를 제거/재등록하지 않고 함수 참조를 DB 기반 구현으로 교체하면
# FastAPI 라우트 등록 순서와 관계없이 항상 동일한 핫키 목록을 반환합니다.
def database_label_hotkeys() -> list[dict[str, str]]:
    return list_hotkeys()["items"]


main_module.label_hotkeys = database_label_hotkeys

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
