from . import collaboration as collaboration_module
from . import main as main_module
from .collaboration import router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .compatibility import ensure_compatibility_triggers
from .data_model import router as normalized_router
from .dataset_browser import list_hotkeys, router as dataset_browser_router
from .scan_manager import router as scan_router, start_background_scan
from .schema_runtime import ensure_schema_ready, install_schema_guard
from .task_worker import worker

app = main_module.app

# Legacy startup performs a full file-system scan on every API restart.
if main_module.startup in app.router.on_startup:
    app.router.on_startup.remove(main_module.startup)

# Replace legacy mutation routes with normalized/background implementations.
_replaced_paths = {"/api/scan", "/api/splits/auto", "/api/exports"}
app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) not in _replaced_paths
]
normalized_router.routes = [
    route for route in normalized_router.routes
    if getattr(route, "path", None) != "/api/scan"
]


def database_label_hotkeys() -> list[dict[str, str]]:
    return list_hotkeys()["items"]


main_module.label_hotkeys = database_label_hotkeys
install_schema_guard()
# collaboration.py imported the original function directly, so replace its
# module-level reference as well.
collaboration_module.ensure_normalized_schema = ensure_schema_ready

app.include_router(normalized_router)
app.include_router(scan_router)
app.include_router(collaboration_router)
app.include_router(collaboration_summary_router)
app.include_router(dataset_browser_router)


def initialize_catalog_task() -> dict:
    """Initialize/migrate the catalog outside the ASGI startup lifecycle."""
    ensure_schema_ready()
    ensure_compatibility_triggers()

    with main_module.connect() as conn:
        image_count = conn.execute(
            "SELECT COUNT(*) FROM images WHERE COALESCE(is_active,1)=1"
        ).fetchone()[0]

    if image_count == 0:
        start_background_scan()

    return {"catalog_ready": True, "image_count": int(image_count)}


@app.on_event("startup")
def initialize_application() -> None:
    # Keep startup deterministic and short: create the legacy base DB, start the
    # worker, enqueue catalog initialization, then immediately let Uvicorn bind.
    main_module.init_db()
    worker.start()
    worker.submit(
        "catalog-initialize",
        initialize_catalog_task,
        dedupe_key="catalog-initialize",
    )
