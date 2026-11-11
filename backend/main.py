# backend/main.py
import os
import time
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings
from backend.app.core.logging import logger
from backend.app.core.database import SessionLocal, ensure_database_exists, engine
from backend.app.models.base import Base
from backend.app.modules.projects.router import ensure_default_project, router as projects_router
from backend.app.modules.audits.router import router as audits_router
from backend.app.modules.batches.router import router as batches_router
from backend.app.modules.api_keys.router import router as api_keys_router
from backend.app.modules.monitoring.router import router as monitoring_router
from backend.routers.predict import router as legacy_predict_router

# OpenTelemetry Tracing Setup
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


if _HAS_OTEL:
    resource = Resource.create(attributes={
        "service.name": settings.OTEL_SERVICE_NAME,
        "deployment.environment": settings.ENVIRONMENT
    })

    # Explicit Tracing Decoupling: Tracing is strictly off unless explicitly enabled
    if settings.ENABLE_TRACING and not settings.DISABLE_MODEL:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True))
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            logger.info(f"OpenTelemetry tracing enabled -> {settings.OTEL_EXPORTER_OTLP_ENDPOINT}")
        except Exception as e:
            logger.warning(f"Could not initialize OTLPSpanExporter ({e}). Falling back to disabled tracer.")
            provider = TracerProvider(resource=resource, sampler=ALWAYS_OFF)
            trace.set_tracer_provider(provider)
    else:
        provider = TracerProvider(resource=resource, sampler=ALWAYS_OFF)
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database & default project exist
    logger.info("Initializing Vietnamese AI Response QA Backend...")
    try:
        ensure_database_exists()
        # Ensure schema tables exist
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            project = ensure_default_project(db)
            logger.info(f"Default project ready: {project.name} ({project.id})")
    except Exception as exc:
        logger.warning(f"Database initialization warning: {exc}")
    yield
    logger.info("Shutting down backend...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    trace_id = None

    if _HAS_OTEL:
        current_span = trace.get_current_span()
        span_context = current_span.get_span_context()
        if span_context and span_context.is_valid:
            trace_id = format(span_context.trace_id, "032x")

    request.state.trace_id = trace_id
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000

    log_msg = f"Path: {request.url.path} Method: {request.method} Status: {response.status_code} Latency: {process_time:.2f}ms"
    if hasattr(logger, "bind"):
        logger.bind(trace_id=trace_id).info(log_msg)
    else:
        logger.info(log_msg)

    return response


# Instrument Prometheus & FastAPI if available
if _HAS_OTEL:
    try:
        Instrumentator().instrument(app).expose(app)
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        logger.warning(f"Instrumentator warning: {exc}")

# CORS Middleware
origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
if not origins or "*" in origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API v1 Routers (Sprint 1 & Sprint 2 MVP)
app.include_router(audits_router, prefix=settings.API_V1_STR)
app.include_router(projects_router, prefix=settings.API_V1_STR)
app.include_router(batches_router, prefix=settings.API_V1_STR)
app.include_router(api_keys_router, prefix=settings.API_V1_STR)
app.include_router(monitoring_router, prefix=settings.API_V1_STR)

# Legacy Route for backward compatibility
app.include_router(legacy_predict_router, prefix="/api", tags=["Legacy"])


@app.get("/health", tags=["System"])
async def health():
    db_status = "connected"
    try:
        with SessionLocal() as db:
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unreachable: {str(e)}"

    return {
        "status": "ok",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": db_status
    }


try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


@app.get("/metrics", tags=["System"])
def metrics():
    if not _HAS_PROMETHEUS:
        return Response(content="# Prometheus client not available\n", media_type="text/plain")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
