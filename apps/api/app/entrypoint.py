from .collaboration import ensure_collaboration_schema, router as collaboration_router
from .main import app

app.include_router(collaboration_router)


@app.on_event("startup")
def initialize_collaboration() -> None:
    ensure_collaboration_schema()
