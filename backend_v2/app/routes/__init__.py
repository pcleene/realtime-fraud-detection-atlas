from app.routes.score import router as score_router
from app.routes.health import router as health_router
from app.routes.mock import router as mock_router
from app.routes.loadtest import router as loadtest_router
from app.routes.config import router as config_router

__all__ = ["score_router", "health_router", "mock_router", "loadtest_router", "config_router"]
