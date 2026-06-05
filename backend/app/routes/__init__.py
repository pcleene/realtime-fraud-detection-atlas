from app.routes.score import router as score_router
from app.routes.health import router as health_router
from app.routes.loadtest import router as loadtest_router

__all__ = ["score_router", "health_router", "loadtest_router"]
