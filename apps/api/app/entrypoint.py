from .collaboration import ensure_collaboration_schema, router as collaboration_router
from .collaboration_summary import router as collaboration_summary_router
from .dataset_browser import router as dataset_browser_router
from .main import app

app.include_router(collaboration_router)
app.include_router(collaboration_summary_router)
app.include_router(dataset_browser_router)


@app.on_event("startup")
def initialize_collaboration() -> None:
    ensure_collaboration_schema()
