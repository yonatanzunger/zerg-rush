"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, agents, saved_agents, credentials, logs
from app.config import get_settings
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title=settings.app_name,
    description="Secure Agent Fleet Management System",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_session_middleware(request: Request, call_next):
    """Finalize trace sessions after request completion."""
    response = await call_next(request)
    if hasattr(request.state, "trace_session"):
        request.state.trace_session.finalize()
    return response


# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(agents.router, prefix="/agents", tags=["Agents"])
app.include_router(saved_agents.router, prefix="/saved-agents", tags=["Saved Agents"])
app.include_router(credentials.router, prefix="/credentials", tags=["Credentials"])
app.include_router(logs.router, prefix="/logs", tags=["Audit Logs"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}
