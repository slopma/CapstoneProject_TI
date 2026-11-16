import logging
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.discovery.connectors import ConnectorError

from app.config import CORS_ORIGINS, INVENTORY_PATH, LOG_LEVEL
from app.api.routers import architecture, migration, discovery, agents

class _CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] [ReqID: %(correlation_id)s] %(message)s",
)
for _handler in logging.root.handlers:
    _handler.addFilter(_CorrelationIdFilter())
logger = logging.getLogger("cloudmove")

app = FastAPI(
    title="CloudMove Enterprise API",
    description="Plataforma web de descubrimiento, modelado CMIR v2.1 y orquestación IaC hacia AWS",
    version="2.0.0",
)

_effective_origins = CORS_ORIGINS if CORS_ORIGINS else ["*"]
_has_wildcard_origin = "*" in _effective_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_effective_origins,
    allow_credentials=not _has_wildcard_origin,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    req_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = req_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = req_id
    return response


@app.exception_handler(ConnectorError)
async def connector_error_handler(request: Request, exc: ConnectorError):
    logger.error("Connector error on %s %s: [%s] %s", request.method, request.url.path, exc.code, exc.message)
    status_code = 404 if exc.code == "GITHUB_NOT_FOUND" else (400 if exc.code in ("GITHUB_REF_NOT_FOUND", "GITHUB_RATE_LIMIT") else 502)
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "code": exc.code},
        headers={"X-Correlation-ID": getattr(request.state, "correlation_id", "-")},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno del servidor: {str(exc)}"},
        headers={"X-Correlation-ID": getattr(request.state, "correlation_id", "-")},
    )


# Include Routers
app.include_router(architecture.router)
app.include_router(migration.router)
app.include_router(discovery.router)
app.include_router(agents.router)


@app.get("/")
def root():
    return {
        "project": "CloudMove",
        "version": "2.0.0",
        "status": "running",
        "architecture_engine": "Hierarchical Graph Level 0-8",
        "docs": "/docs",
    }


@app.get("/health")
@app.get("/api/health")
@app.get("/api/v1/health")
def health():
    return {
        "status": "healthy",
        "inventory_loaded": INVENTORY_PATH.exists(),
        "inventory_path": str(INVENTORY_PATH),
    }
