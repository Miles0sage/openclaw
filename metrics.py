"""
Metrics collection system for OpenClaw gateway
Provides Prometheus-compatible metrics endpoint
"""

import time
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path

class MetricsCollector:
    """Collects and reports gateway metrics"""
    
    def __init__(self):
        self.request_count = 0
        self.agent_calls = defaultdict(int)
        self.total_cost_usd = 0.0
        self.active_sessions = set()
        self.requests_by_ip = defaultdict(int)
        self.request_timestamps = defaultdict(list)  # For rate limiting
        self.start_time = time.time()
        
    def record_request(self, ip: str, endpoint: str):
        """Record HTTP request"""
        self.request_count += 1
        self.requests_by_ip[ip] += 1
        self.request_timestamps[ip].append(time.time())
        
    def record_agent_call(self, agent_id: str):
        """Record agent invocation"""
        self.agent_calls[agent_id] += 1
        
    def record_cost(self, cost_usd: float):
        """Record API cost"""
        self.total_cost_usd += cost_usd
        
    def record_session(self, session_key: str):
        """Track active session"""
        self.active_sessions.add(session_key)
        
    def get_uptime_seconds(self) -> int:
        """Get gateway uptime in seconds"""
        return int(time.time() - self.start_time)
    
    def check_rate_limit(self, ip: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
        """Check if IP has exceeded rate limit (30 req/min default)"""
        now = time.time()
        cutoff = now - window_seconds
        
        # Clean old requests
        self.request_timestamps[ip] = [t for t in self.request_timestamps[ip] if t > cutoff]
        
        # Check limit
        return len(self.request_timestamps[ip]) < max_requests
    
    def get_prometheus_metrics(self) -> str:
        """Return metrics in Prometheus format"""
        lines = [
            "# HELP openclaw_requests_total Total HTTP requests",
            f"openclaw_requests_total {self.request_count}",
            "",
            "# HELP openclaw_agent_calls_total Total agent invocations",
        ]
        
        for agent_id, count in sorted(self.agent_calls.items()):
            lines.append(f'openclaw_agent_calls_total{{agent="{agent_id}"}} {count}')
        
        lines.extend([
            "",
            "# HELP openclaw_cost_usd Total API costs in USD",
            f"openclaw_cost_usd {self.total_cost_usd:.4f}",
            "",
            "# HELP openclaw_active_sessions Active session count",
            f"openclaw_active_sessions {len(self.active_sessions)}",
            "",
            "# HELP openclaw_gateway_uptime_seconds Gateway uptime in seconds",
            f"openclaw_gateway_uptime_seconds {self.get_uptime_seconds()}",
        ])
        
        return "\n".join(lines) + "\n"
    
    def load_from_disk(self):
        """Load metrics from persistent storage (optional)"""
        cost_file = Path("/tmp/openclaw_costs.jsonl")
        if cost_file.exists():
            try:
                with open(cost_file, "r") as f:
                    for line in f:
                        data = json.loads(line)
                        self.total_cost_usd += data.get("cost_usd", 0)
            except Exception as e:
                print(f"Warning: Could not load costs from disk: {e}")

# Global metrics instance
metrics = MetricsCollector()
