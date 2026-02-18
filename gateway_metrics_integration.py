"""
Gateway Metrics Integration Module
Provides middleware and routes for metrics collection
"""

import time
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Optional
import os
from metrics_collector import get_metrics_collector, record_metric, init_metrics_collector

class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect request metrics"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics for health checks and metrics endpoints
        skip_paths = {'/health', '/api/metrics', '/dashboard.html', '/static'}
        if any(request.url.path.startswith(p) for p in skip_paths):
            return await call_next(request)
        
        start_time = time.time()
        status_code = 500
        error = None
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as e:
            error = str(e)
            status_code = 500
            raise
        finally:
            # Record metric
            response_time_ms = (time.time() - start_time) * 1000
            record_metric(
                method=request.method,
                endpoint=request.url.path,
                status_code=status_code,
                response_time_ms=response_time_ms,
                error=error if error else None
            )

def setup_metrics(app: FastAPI, static_dir: Optional[str] = None) -> None:
    """Setup metrics collection and routes"""
    
    # Initialize collector
    init_metrics_collector()
    
    # Add middleware
    app.add_middleware(MetricsMiddleware)
    
    # Mount static files for dashboard
    if static_dir and os.path.isdir(static_dir):
        try:
            app.mount("/static", StaticFiles(directory=static_dir), name="static")
        except Exception as e:
            print(f"Warning: Failed to mount static files: {e}")
    
    # Metrics endpoints
    @app.get("/api/metrics/summary")
    async def get_metrics_summary():
        """Get current metrics summary"""
        collector = get_metrics_collector()
        return JSONResponse(collector.to_dict())
    
    @app.get("/api/metrics/snapshot")
    async def get_metrics_snapshot():
        """Get current metrics snapshot"""
        collector = get_metrics_collector()
        snapshot = collector.get_snapshot()
        return JSONResponse({
            'snapshot': {
                'timestamp': snapshot.timestamp,
                'total_requests': snapshot.total_requests,
                'average_response_time': snapshot.average_response_time,
                'error_rate': snapshot.error_rate,
                'total_cost': snapshot.total_cost,
                'active_sessions': snapshot.active_sessions,
                'gateway_online': snapshot.gateway_online,
                'gateway_uptime': snapshot.gateway_uptime
            }
        })
    
    @app.get("/api/metrics/reset")
    async def reset_metrics():
        """Reset all metrics"""
        global _metrics_collector
        from metrics_collector import MetricsCollector
        collector = get_metrics_collector()
        collector.metrics = []
        return JSONResponse({'status': 'reset', 'message': 'All metrics cleared'})
    
    @app.post("/api/metrics/budget")
    async def set_budget(request: Request):
        """Set monthly budget"""
        data = await request.json()
        budget = data.get('budget', 1000.0)
        collector = get_metrics_collector()
        collector.set_monthly_budget(budget)
        return JSONResponse({'status': 'success', 'budget': budget})
    
    @app.get("/dashboard.html")
    async def get_dashboard():
        """Serve dashboard HTML"""
        static_dir = static_dir or os.path.join(os.path.dirname(__file__), 'src', 'static')
        dashboard_path = os.path.join(static_dir, 'dashboard.html')
        
        if os.path.isfile(dashboard_path):
            return FileResponse(dashboard_path, media_type="text/html")
        else:
            return JSONResponse(
                {'error': f'Dashboard not found at {dashboard_path}'},
                status_code=404
            )

def update_session_count(session_id: str, active: bool = True) -> None:
    """Update active session count"""
    collector = get_metrics_collector()
    collector.set_active_session(session_id, active)

def record_request_metric(
    method: str,
    endpoint: str,
    status_code: int,
    response_time_ms: float,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: float = 0.0,
    error: Optional[str] = None,
) -> None:
    """Record a request metric with full details"""
    record_metric(
        method=method,
        endpoint=endpoint,
        status_code=status_code,
        response_time_ms=response_time_ms,
        agent=agent,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
        error=error
    )
