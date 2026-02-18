"""
Metrics Collector for OpenClaw Gateway
Tracks requests, response times, errors, costs, and agent usage
"""

import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import threading

@dataclass
class RequestMetric:
    """Individual request metric"""
    timestamp: float
    method: str
    endpoint: str
    status_code: int
    response_time_ms: float
    agent: Optional[str] = None
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    error: Optional[str] = None

@dataclass
class MetricsSnapshot:
    """Current metrics snapshot"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    p95_response_time: float = 0.0
    p99_response_time: float = 0.0
    error_rate: float = 0.0
    error_count: int = 0
    total_cost: float = 0.0
    monthly_budget: float = 0.0
    active_sessions: int = 0
    gateway_online: bool = True
    gateway_uptime: int = 0
    cost_by_model: Dict[str, float] = field(default_factory=dict)
    response_time_distribution: Dict[str, int] = field(default_factory=dict)
    agent_usage: Dict[str, int] = field(default_factory=dict)
    endpoint_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: str = ""

class MetricsCollector:
    """Collects and aggregates metrics"""
    
    def __init__(self, retention_minutes: int = 60):
        self.retention_minutes = retention_minutes
        self.metrics: List[RequestMetric] = []
        self.lock = threading.RLock()
        self.start_time = time.time()
        self.monthly_budget = 1000.0  # Default monthly budget in dollars
        self.active_sessions: set = set()
        
    def record_request(
        self,
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
        """Record a new request metric"""
        with self.lock:
            metric = RequestMetric(
                timestamp=time.time(),
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
            self.metrics.append(metric)
            self._cleanup_old_metrics()
    
    def set_active_session(self, session_id: str, active: bool = True) -> None:
        """Track active sessions"""
        with self.lock:
            if active:
                self.active_sessions.add(session_id)
            else:
                self.active_sessions.discard(session_id)
    
    def get_active_session_count(self) -> int:
        """Get number of active sessions"""
        with self.lock:
            return len(self.active_sessions)
    
    def set_monthly_budget(self, budget: float) -> None:
        """Set monthly budget"""
        with self.lock:
            self.monthly_budget = budget
    
    def _cleanup_old_metrics(self) -> None:
        """Remove metrics older than retention window"""
        cutoff_time = time.time() - (self.retention_minutes * 60)
        self.metrics = [m for m in self.metrics if m.timestamp > cutoff_time]
    
    def get_snapshot(self) -> MetricsSnapshot:
        """Get current metrics snapshot"""
        with self.lock:
            self._cleanup_old_metrics()
            
            if not self.metrics:
                return MetricsSnapshot(
                    gateway_online=True,
                    gateway_uptime=int(time.time() - self.start_time),
                    monthly_budget=self.monthly_budget,
                    active_sessions=self.get_active_session_count(),
                    timestamp=datetime.now().isoformat()
                )
            
            # Calculate basic metrics
            total = len(self.metrics)
            successful = sum(1 for m in self.metrics if 200 <= m.status_code < 300)
            failed = sum(1 for m in self.metrics if m.status_code >= 400)
            
            # Response times
            response_times = sorted([m.response_time_ms for m in self.metrics])
            avg_response = sum(response_times) / len(response_times) if response_times else 0
            p95_idx = int(len(response_times) * 0.95)
            p99_idx = int(len(response_times) * 0.99)
            p95_response = response_times[p95_idx] if p95_idx < len(response_times) else response_times[-1]
            p99_response = response_times[p99_idx] if p99_idx < len(response_times) else response_times[-1]
            
            # Error rate
            error_rate = failed / total if total > 0 else 0.0
            
            # Costs
            total_cost = sum(m.cost for m in self.metrics)
            cost_by_model = defaultdict(float)
            for m in self.metrics:
                if m.model:
                    cost_by_model[m.model] += m.cost
            
            # Response time distribution
            dist = defaultdict(int)
            for rt in response_times:
                if rt < 100:
                    dist['<100ms'] += 1
                elif rt < 500:
                    dist['100-500ms'] += 1
                elif rt < 1000:
                    dist['500-1000ms'] += 1
                else:
                    dist['>1000ms'] += 1
            
            # Agent usage
            agent_usage = defaultdict(int)
            for m in self.metrics:
                if m.agent:
                    agent_usage[m.agent] += 1
            
            # Endpoint usage
            endpoint_usage = defaultdict(int)
            for m in self.metrics:
                endpoint_usage[m.endpoint] += 1
            
            # Uptime
            uptime = int(time.time() - self.start_time)
            
            return MetricsSnapshot(
                total_requests=total,
                successful_requests=successful,
                failed_requests=failed,
                average_response_time=avg_response,
                p95_response_time=p95_response,
                p99_response_time=p99_response,
                error_rate=error_rate,
                error_count=failed,
                total_cost=total_cost,
                monthly_budget=self.monthly_budget,
                active_sessions=self.get_active_session_count(),
                gateway_online=True,
                gateway_uptime=uptime,
                cost_by_model=dict(cost_by_model),
                response_time_distribution=dict(dist),
                agent_usage=dict(agent_usage),
                endpoint_usage=dict(endpoint_usage),
                timestamp=datetime.now().isoformat()
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary"""
        snapshot = self.get_snapshot()
        return {
            'metrics': {
                'total_requests': snapshot.total_requests,
                'successful_requests': snapshot.successful_requests,
                'failed_requests': snapshot.failed_requests,
                'average_response_time': round(snapshot.average_response_time, 2),
                'p95_response_time': round(snapshot.p95_response_time, 2),
                'p99_response_time': round(snapshot.p99_response_time, 2),
                'error_rate': round(snapshot.error_rate, 4),
                'error_count': snapshot.error_count,
                'total_cost': round(snapshot.total_cost, 2),
                'monthly_budget': round(snapshot.monthly_budget, 2),
                'active_sessions': snapshot.active_sessions,
                'gateway_online': snapshot.gateway_online,
                'gateway_uptime': snapshot.gateway_uptime,
                'cost_by_model': {k: round(v, 2) for k, v in snapshot.cost_by_model.items()},
                'response_time_distribution': snapshot.response_time_distribution,
                'agent_usage': snapshot.agent_usage,
                'endpoint_usage': snapshot.endpoint_usage,
                'timestamp': snapshot.timestamp
            }
        }

# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None

def init_metrics_collector(retention_minutes: int = 60) -> MetricsCollector:
    """Initialize global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector(retention_minutes=retention_minutes)
    return _metrics_collector

def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector

def record_metric(
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
    """Record a request metric"""
    collector = get_metrics_collector()
    collector.record_request(
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

def get_metrics_summary() -> Dict[str, Any]:
    """Get current metrics summary"""
    collector = get_metrics_collector()
    return collector.to_dict()
