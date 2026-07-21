from . import collaboration as collaboration_module
from . import collaboration_summary as collaboration_summary_module
from . import compatibility as compatibility_module
from . import data_model as data_model_module
from . import dataset_browser as dataset_browser_module
from . import export_manager as export_manager_module
from . import folder_work as folder_work_module
from . import incremental_scan as incremental_scan_module
from . import main as main_module
from .activity_logging import ensure_activity_logging_triggers
from .collaboration import router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .compatibility import ensure_compatibility_triggers
from .data_model import router as normalized_router
from .dataset_browser import list_hotkeys, router as dataset_browser_router
from .export_manager import router as export_router
from .folder_work import ensure_folder_work_schema, router as folder_work_router
from .incremental_scan import router as incremental_scan_router
from .resilient_db import connect_database
from .scan_manager import router as scan_router, start_background_scan
from .schema_runtime import ensure_schema_ready, install_schema_guard
from .task_worker import worker

app = main_module.app


def resilient_connect():
    return connect_database(main_module.DB_PATH)


main_module.connect = resilient_connect
data_model_module.connect = resilient_connect
collaboration_module.connect = resilient_connect
collaboration_summary_module.connect = resilient_connect
compatibility_module.connect = resilient_connect
dataset_browser_module.connect = resilient_connect
export_manager_module.connect = resilient_connect
folder_work_module.connect = resilient_connect
incremental_scan_module.data_model.connect = resilient_connect

if main_module.startup in app.router.on_startup:
    app.router.on_startup.remove(main_module.startup)

_replaced_paths = {"/api/scan", "/api/splits/auto", "/api/exports"}
app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) not in _replaced_paths
]
normalized_router.routes = [
    route for route in normalized_router.routes
    if getattr(route, "path", None) not in {"/api/scan", "/api/exports"}
]


def database_label_hotkeys() -> list[dict[str, str]]:
    return list_hotkeys()["items"]


main_module.label_hotkeys = database_label_hotkeys
install_schema_guard()
collaboration_module.ensure_normalized_schema = ensure_schema_ready
collaboration_summary_module.ensure_normalized_schema = ensure_schema_ready
dataset_browser_module.ensure_normalized_schema = ensure_schema_ready
export_manager_module.ensure_normalized_schema = ensure_schema_ready
folder_work_module.ensure_normalized_schema = ensure_schema_ready

app.include_router(normalized_router)
app.include_router(scan_router)
app.include_router(incremental_scan_router)
app.include_router(export_router)
app.include_router(collaboration_router)
app.include_router(collaboration_summary_router)
app.include_router(dataset_browser_router)
app.include_router(folder_work_router)


def initialize_catalog_task() -> dict:
    ensure_schema_ready()
    ensure_compatibility_triggers()
    ensure_folder_work_schema()
    ensure_activity_logging_triggers()

    with main_module.connect() as conn:
        image_count = conn.execute(
            "SELECT COUNT(*) FROM images WHERE COALESCE(is_active,1)=1"
        ).fetchone()[0]

    if image_count == 0:
        start_background_scan()

    return {"catalog_ready": True, "image_count": int(image_count)}


@app.on_event("startup")
def initialize_application() -> None:
    main_module.init_db()
    worker.start()
    worker.submit(
        "catalog-initialize",
        initialize_catalog_task,
        dedupe_key="catalog-initialize",
    )
