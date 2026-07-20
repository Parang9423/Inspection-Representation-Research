from . import main as main_module
from .collaboration import router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .compatibility import ensure_compatibility_triggers
from .data_model import ensure_normalized_schema, router as normalized_router, scan_catalog
from .dataset_browser import list_hotkeys, router as dataset_browser_router

app = main_module.app

# Legacy startup performs a full file-system scan on every API restart.
if main_module.startup in app.router.on_startup:
    app.router.on_startup.remove(main_module.startup)

# Replace legacy mutation routes with normalized implementations.
_replaced_paths = {"/api/scan", "/api/splits/auto", "/api/exports"}
app.router.routes = [
    route for route in app.router.routes
    if getattr(route, "path", None) not in _replaced_paths
]


def database_label_hotkeys() -> list[dict[str, str]]:
    return list_hotkeys()["items"]


main_module.label_hotkeys = database_label_hotkeys

app.include_router(normalized_router)
app.include_router(collaboration_router)
app.include_router(collaboration_summary_router)
app.include_router(dataset_browser_router)


@app.on_event("startup")
def initialize_application() -> None:
    main_module.init_db()
    ensure_normalized_schema()
    ensure_compatibility_triggers()

    # Only the first run scans the source tree. Existing DB content is served immediately.
    with main_module.connect() as conn:
        image_count = conn.execute(
            "SELECT COUNT(*) FROM images WHERE COALESCE(is_active,1)=1"
        ).fetchone()[0]

    if image_count == 0:
        scan_catalog()
