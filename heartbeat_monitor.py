"""
Heartbeat Monitor Integration for OpenClaw Gateway
Manages agent health checks and auto-recovery
"""

import os
import json
import logging
import asyncio
import subprocess
import threading
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("heartbeat_monitor")


class PythonHeartbeatMonitor:
    """Python-based heartbeat monitor for agent health checks"""

    def __init__(self, check_interval_ms: int = 30000, stale_threshold_ms: int = 5 * 60 * 1000, timeout_threshold_ms: int = 30 * 60 * 1000):
        """
        Initialize heartbeat monitor

        Args:
            check_interval_ms: How often to run health checks (default: 30s)
            stale_threshold_ms: Idle >5min is stale (default: 5 min)
            timeout_threshold_ms: Running >30min is timeout (default: 30 min)
        """
        self.check_interval_ms = check_interval_ms
        self.stale_threshold_ms = stale_threshold_ms
        self.timeout_threshold_ms = timeout_threshold_ms

        self.in_flight_agents: Dict[str, dict] = {}
        self.stale_counts: Dict[str, int] = {}
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.alerts_file = "/tmp/alerts.json"

    def start(self) -> None:
        """Start the background health check loop"""
        if self.is_running:
            logger.warning("HeartbeatMonitor: already running")
            return

        self.is_running = True
        logger.info(f"⏱️ HeartbeatMonitor: started (check interval: {self.check_interval_ms}ms)")

        # Start background thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop(self) -> None:
        """Stop the background health check loop"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
            self.monitor_thread = None
        logger.info("⏱️ HeartbeatMonitor: stopped")

    def register_agent(self, agent_id: str, task_id: Optional[str] = None) -> None:
        """Register an in-flight agent task"""
        now_ms = int(datetime.now().timestamp() * 1000)
        self.in_flight_agents[agent_id] = {
            "agent_id": agent_id,
            "started_at": now_ms,
            "last_activity_at": now_ms,
            "task_id": task_id,
            "status": "running"
        }
        self.stale_counts.pop(agent_id, None)
        logger.debug(f"Registered agent: {agent_id}")

    def update_activity(self, agent_id: str) -> None:
        """Update last activity timestamp for an agent"""
        if agent_id in self.in_flight_agents:
            now_ms = int(datetime.now().timestamp() * 1000)
            self.in_flight_agents[agent_id]["last_activity_at"] = now_ms
            self.in_flight_agents[agent_id]["status"] = "running"

    def mark_idle(self, agent_id: str) -> None:
        """Mark an agent as idle (waiting for something)"""
        if agent_id in self.in_flight_agents:
            self.in_flight_agents[agent_id]["status"] = "idle"

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister an in-flight agent task"""
        self.in_flight_agents.pop(agent_id, None)
        self.stale_counts.pop(agent_id, None)

    def get_in_flight_agents(self) -> List[dict]:
        """Get all in-flight agents"""
        return list(self.in_flight_agents.values())

    def _monitor_loop(self) -> None:
        """Background monitoring loop"""
        while self.is_running:
            try:
                self._run_health_checks()
            except Exception as err:
                logger.error(f"HeartbeatMonitor: error in health check loop: {err}")

            # Sleep for check interval (convert ms to seconds)
            asyncio.run(asyncio.sleep(self.check_interval_ms / 1000))

    def _run_health_checks(self) -> None:
        """Run health checks on all in-flight agents"""
        now_ms = int(datetime.now().timestamp() * 1000)
        agents_to_check = list(self.in_flight_agents.items())

        for agent_id, agent in agents_to_check:
            try:
                elapsed_ms = now_ms - agent["started_at"]
                idle_ms = now_ms - agent["last_activity_at"]

                # Check for timeout: task running >timeout_threshold
                if elapsed_ms > self.timeout_threshold_ms:
                    self._handle_timeout(agent_id, agent, elapsed_ms)
                    continue  # Don't also alert on stale

                # Check for stale: idle >stale_threshold but still <timeout_threshold
                if idle_ms > self.stale_threshold_ms and elapsed_ms < self.timeout_threshold_ms:
                    self._handle_stale(agent_id, agent, idle_ms)

            except Exception as err:
                logger.error(f"HeartbeatMonitor: error checking agent {agent_id}: {err}")

    def _handle_stale(self, agent_id: str, agent: dict, idle_ms: int) -> None:
        """Handle stale agent detection"""
        stale_count = self.stale_counts.get(agent_id, 0)

        # Only alert once per stale agent by default
        if stale_count > 0:
            return

        idle_seconds = idle_ms // 1000
        message = f"⚠️ Stale agent detected: {agent_id} idle for {idle_seconds}s"
        logger.warning(message)

        # Create alert
        self._create_alert("warning", message, {
            "agentId": agent_id,
            "idleMs": idle_ms,
            "idleSeconds": idle_seconds,
            "taskId": agent.get("task_id"),
            "source": "heartbeat-monitor"
        })

        self.stale_counts[agent_id] = stale_count + 1

    def _handle_timeout(self, agent_id: str, agent: dict, elapsed_ms: int) -> None:
        """Handle timeout agent detection and recovery"""
        elapsed_seconds = elapsed_ms // 1000
        elapsed_minutes = elapsed_ms // 60000
        message = f"❌ Timeout: agent {agent_id} running for {elapsed_minutes}min (task: {agent.get('task_id', 'unknown')})"

        logger.error(message)

        # Create error alert
        self._create_alert("error", message, {
            "agentId": agent_id,
            "taskId": agent.get("task_id"),
            "elapsedMs": elapsed_ms,
            "elapsedSeconds": elapsed_seconds,
            "elapsedMinutes": elapsed_minutes,
            "source": "heartbeat-monitor"
        })

        # Auto-recover: unregister the stale task
        self.in_flight_agents.pop(agent_id, None)
        self.stale_counts.pop(agent_id, None)

        logger.info(f"   ✅ Recovered: agent {agent_id} removed from in-flight, ready for next task")

    def _create_alert(self, alert_type: str, message: str, context: dict) -> None:
        """Create and store an alert"""
        try:
            alerts = []
            if os.path.exists(self.alerts_file):
                try:
                    with open(self.alerts_file, 'r') as f:
                        alerts = json.load(f)
                except:
                    alerts = []

            alert = {
                "id": f"alert-{int(datetime.now().timestamp() * 1000)}",
                "type": alert_type,
                "timestamp": datetime.now().isoformat(),
                "message": message,
                "context": context,
                "acknowledged": False,
                "source": "heartbeat-monitor"
            }

            alerts.append(alert)

            # Keep only last 1000 alerts
            alerts = alerts[-1000:]

            with open(self.alerts_file, 'w') as f:
                json.dump(alerts, f)

        except Exception as err:
            logger.error(f"Failed to create alert: {err}")


# Global heartbeat monitor instance
_heartbeat_monitor: Optional[PythonHeartbeatMonitor] = None


def init_heartbeat_monitor(
    check_interval_ms: int = 30000,
    stale_threshold_ms: int = 5 * 60 * 1000,
    timeout_threshold_ms: int = 30 * 60 * 1000
) -> PythonHeartbeatMonitor:
    """Initialize and start the global heartbeat monitor"""
    global _heartbeat_monitor

    if _heartbeat_monitor:
        logger.warning("HeartbeatMonitor: already initialized")
        return _heartbeat_monitor

    _heartbeat_monitor = PythonHeartbeatMonitor(
        check_interval_ms=check_interval_ms,
        stale_threshold_ms=stale_threshold_ms,
        timeout_threshold_ms=timeout_threshold_ms
    )
    _heartbeat_monitor.start()
    return _heartbeat_monitor


def get_heartbeat_monitor() -> Optional[PythonHeartbeatMonitor]:
    """Get the global heartbeat monitor instance"""
    return _heartbeat_monitor


def stop_heartbeat_monitor() -> None:
    """Stop the global heartbeat monitor"""
    global _heartbeat_monitor
    if _heartbeat_monitor:
        _heartbeat_monitor.stop()
        _heartbeat_monitor = None
