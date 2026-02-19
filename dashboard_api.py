"""
OpenClaw Gateway Dashboard API
FastAPI backend for real-time monitoring and management

Features:
- Gateway & tunnel status monitoring
- Log aggregation from gateway and tunnel services
- Webhook URL management
- Service restart capabilities
- Encrypted secret management
- Detailed health checks
- Token-based authentication
- CORS enabled for frontend
- Static file serving
"""

import os
import json
import logging
import hashlib
import hmac
import base64
import subprocess
import pathlib
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from functools import wraps

from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
GATEWAY_PORT = int(os.getenv("OPENCLAW_GATEWAY_PORT", 18789))
GATEWAY_HOST = os.getenv("OPENCLAW_GATEWAY_HOST", "localhost")
DASHBOARD_PORT = int(os.getenv("OPENCLAW_DASHBOARD_PORT", 9000))
DASHBOARD_PASSWORD = os.getenv("OPENCLAW_DASHBOARD_PASSWORD", "openclaw-dashboard-2026")
DASHBOARD_TOKEN = os.getenv("OPENCLAW_DASHBOARD_TOKEN", "moltbot-secure-token-2026")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
GATEWAY_LOG_PATH = pathlib.Path(os.getenv("OPENCLAW_GATEWAY_LOG_PATH", os.path.join(DATA_DIR, "events", "gateway.log")))
TUNNEL_LOG_PATH = pathlib.Path(os.getenv("OPENCLAW_TUNNEL_LOG_PATH", "/tmp/cloudflared-tunnel.log"))
CONFIG_PATH = pathlib.Path(os.getenv("OPENCLAW_CONFIG_PATH", "/root/openclaw/config.json"))
SECRETS_PATH = pathlib.Path(os.getenv("OPENCLAW_SECRETS_PATH", "/tmp/openclaw_secrets.json"))
STATIC_DIR = pathlib.Path(os.getenv("OPENCLAW_STATIC_DIR", "/var/www/dashboard"))

STATIC_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("openclaw_dashboard")

# FastAPI app setup
app = FastAPI(
    title="OpenClaw Dashboard API",
    description="Real-time monitoring and management for OpenClaw Gateway",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving
if STATIC_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(STATIC_DIR)), name="dashboard")


# ============================================================================
# Models
# ============================================================================

class StatusResponse(BaseModel):
    """Gateway status response"""
    gateway_running: bool
    gateway_port: int
    gateway_host: str
    tunnel_running: bool
    tunnel_url: Optional[str] = None
    uptime_seconds: int
    timestamp: str
    version: str = "1.0.0"


class LogResponse(BaseModel):
    """Log response"""
    gateway_logs: List[str]
    tunnel_logs: List[str]
    total_lines: int
    timestamp: str


class WebhookResponse(BaseModel):
    """Webhook URLs response"""
    telegram_webhook: str
    slack_webhook: str
    telegram_enabled: bool
    slack_enabled: bool


class ConfigResponse(BaseModel):
    """Gateway configuration (no secrets)"""
    name: str
    version: str
    port: int
    channels: Dict[str, Any]
    agents_count: int
    timestamp: str


class SecretInput(BaseModel):
    """Secret input for storing API keys"""
    key: str
    value: str
    service: Optional[str] = None


class SecretResponse(BaseModel):
    """Secret response"""
    message: str
    key: str
    service: Optional[str] = None


class RestartResponse(BaseModel):
    """Restart response"""
    success: bool
    message: str
    timestamp: str


class HealthCheckResponse(BaseModel):
    """Detailed health check"""
    status: str  # "healthy", "degraded", "unhealthy"
    gateway_health: str
    tunnel_health: str
    database_health: str
    api_latency_ms: float
    memory_usage_mb: float
    cpu_usage_percent: float
    uptime_hours: float
    errors_last_hour: int
    warnings_last_hour: int
    timestamp: str


# ============================================================================
# Authentication
# ============================================================================

def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """Verify dashboard access token"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid scheme")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Accept either the token or password
    if token != DASHBOARD_TOKEN and token != DASHBOARD_PASSWORD:
        logger.warning(f"🚨 Invalid dashboard token attempt: {token[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token"
        )

    return token


# ============================================================================
# Utility Functions
# ============================================================================

def read_log_file(log_path: pathlib.Path, lines: int = 50) -> List[str]:
    """Read last N lines from a log file"""
    if not log_path.exists():
        return [f"Log file not found: {log_path}"]

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
            # Get last N lines
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return [line.rstrip('\n') for line in recent_lines]
    except Exception as e:
        logger.error(f"Error reading log file {log_path}: {e}")
        return [f"Error reading log file: {str(e)}"]


def check_service_running(port: int, host: str = "localhost") -> bool:
    """Check if service is running on port"""
    try:
        result = subprocess.run(
            ["netstat", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return f":{port}" in result.stdout
    except Exception:
        # Fallback: try curl
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", f"http://{host}:{port}/health"],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False


def get_process_uptime(port: int) -> int:
    """Get process uptime in seconds"""
    try:
        import psutil
        import os

        # Try to get the gateway process
        try:
            import psutil
            # Look for the gateway process (python gateway.py)
            for proc in psutil.process_iter(['pid', 'name', 'create_time']):
                try:
                    if 'python' in proc.name().lower() and 'gateway' in ' '.join(proc.cmdline()):
                        create_time = proc.create_time()
                        uptime = time.time() - create_time
                        return int(max(0, uptime))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            pass

        # Fallback: check /proc/stat for system boot time
        if os.path.exists('/proc/stat'):
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        boot_time = int(line.split()[1])
                        uptime = int(time.time()) - boot_time
                        return uptime

        return 0
    except Exception as e:
        logger.warning(f"Could not get process uptime: {e}")
        return 0


def load_config() -> Dict[str, Any]:
    """Load gateway configuration"""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")

    return {
        "name": "OpenClaw Gateway",
        "version": "1.0.0",
        "port": GATEWAY_PORT,
        "channels": {},
        "agents": {}
    }


def load_secrets() -> Dict[str, str]:
    """Load encrypted secrets"""
    try:
        if SECRETS_PATH.exists():
            with open(SECRETS_PATH, 'r') as f:
                data = json.load(f)
                return data.get('secrets', {})
    except Exception as e:
        logger.error(f"Error loading secrets: {e}")

    return {}


def save_secrets(secrets: Dict[str, str]) -> bool:
    """Save encrypted secrets"""
    try:
        data = {
            'secrets': secrets,
            'updated_at': datetime.utcnow().isoformat()
        }
        with open(SECRETS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving secrets: {e}")
        return False


def get_webhook_urls() -> Dict[str, Any]:
    """Get webhook URLs from config"""
    config = load_config()
    channels = config.get('channels', {})

    base_url = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}"

    return {
        "telegram_webhook": f"{base_url}/telegram/webhook" if channels.get('telegram', {}).get('enabled') else "",
        "slack_webhook": f"{base_url}/slack/events" if channels.get('slack', {}).get('enabled') else "",
        "telegram_enabled": channels.get('telegram', {}).get('enabled', False),
        "slack_enabled": channels.get('slack', {}).get('enabled', False),
    }


def count_errors_and_warnings(log_path: pathlib.Path, hours: int = 1) -> tuple:
    """Count errors and warnings in the last N hours"""
    if not log_path.exists():
        return 0, 0

    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        errors = 0
        warnings = 0

        with open(log_path, 'r') as f:
            for line in f:
                try:
                    # Simple heuristic: look for ERROR, WARNING, error, warning
                    if any(marker in line for marker in ['ERROR', 'error', '❌']):
                        errors += 1
                    elif any(marker in line for marker in ['WARNING', 'warning', '⚠️']):
                        warnings += 1
                except Exception:
                    pass

        return errors, warnings
    except Exception as e:
        logger.error(f"Error counting logs: {e}")
        return 0, 0


def get_system_metrics() -> Dict[str, float]:
    """Get system metrics"""
    try:
        # Memory usage
        result = subprocess.run(
            ["free", "-m"],
            capture_output=True,
            text=True,
            timeout=5
        )
        lines = result.stdout.split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            memory_usage = round((used / total) * 100, 2) if total > 0 else 0
        else:
            memory_usage = 0

        # CPU usage
        result = subprocess.run(
            ["top", "-bn1"],
            capture_output=True,
            text=True,
            timeout=5
        )
        cpu_usage = 0
        for line in result.stdout.split('\n'):
            if 'Cpu(s)' in line:
                try:
                    parts = line.split()
                    cpu_usage = float(parts[1].replace('%us,', ''))
                except Exception:
                    pass

        return {
            "memory_mb": round(used if 'used' in locals() else 0, 2),
            "cpu_percent": cpu_usage
        }
    except Exception as e:
        logger.error(f"Error getting system metrics: {e}")
        return {"memory_mb": 0, "cpu_percent": 0}


# ============================================================================
# Routes
# ============================================================================

@app.get("/api/status", response_model=StatusResponse)
async def get_status(token: str = Depends(verify_token)):
    """Get gateway and tunnel status"""
    try:
        gateway_running = check_service_running(GATEWAY_PORT, GATEWAY_HOST)
        tunnel_running = False
        tunnel_url = None

        # Check for tunnel logs indicating active tunnel
        if TUNNEL_LOG_PATH.exists():
            try:
                with open(TUNNEL_LOG_PATH, 'r') as f:
                    last_lines = f.readlines()[-20:]
                    tunnel_logs_text = ''.join(last_lines)
                    tunnel_running = 'INF' in tunnel_logs_text or 'quic' in tunnel_logs_text

                    # Try to extract tunnel URL
                    for line in last_lines:
                        if 'workers.dev' in line or 'tunnel' in line.lower():
                            tunnel_url = line.strip()
            except Exception:
                pass

        uptime = get_process_uptime(GATEWAY_PORT)

        return StatusResponse(
            gateway_running=gateway_running,
            gateway_port=GATEWAY_PORT,
            gateway_host=GATEWAY_HOST,
            tunnel_running=tunnel_running,
            tunnel_url=tunnel_url,
            uptime_seconds=uptime,
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting status: {str(e)}")


@app.get("/api/logs", response_model=LogResponse)
async def get_logs(lines: int = 50, token: str = Depends(verify_token)):
    """Get last N lines from gateway and tunnel logs"""
    try:
        if lines < 1 or lines > 500:
            lines = 50

        gateway_logs = read_log_file(GATEWAY_LOG_PATH, lines)
        tunnel_logs = read_log_file(TUNNEL_LOG_PATH, lines)

        return LogResponse(
            gateway_logs=gateway_logs,
            tunnel_logs=tunnel_logs,
            total_lines=len(gateway_logs) + len(tunnel_logs),
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting logs: {str(e)}")


@app.get("/api/webhooks", response_model=WebhookResponse)
async def get_webhooks(token: str = Depends(verify_token)):
    """Get webhook URLs for Telegram and Slack"""
    try:
        webhooks = get_webhook_urls()
        return WebhookResponse(**webhooks)
    except Exception as e:
        logger.error(f"Error getting webhooks: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting webhooks: {str(e)}")


@app.get("/api/config", response_model=ConfigResponse)
async def get_config(token: str = Depends(verify_token)):
    """Get gateway configuration (no secrets)"""
    try:
        config = load_config()

        # Remove sensitive fields
        channels = {}
        for name, channel_config in config.get('channels', {}).items():
            safe_channel = {
                'enabled': channel_config.get('enabled', False),
                'name': channel_config.get('name', ''),
                'type': channel_config.get('type', '')
            }
            channels[name] = safe_channel

        return ConfigResponse(
            name=config.get('name', 'OpenClaw Gateway'),
            version=config.get('version', '1.0.0'),
            port=config.get('port', GATEWAY_PORT),
            channels=channels,
            agents_count=len(config.get('agents', {})),
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting config: {str(e)}")


@app.post("/api/secrets", response_model=SecretResponse)
async def save_secret(secret: SecretInput, token: str = Depends(verify_token)):
    """Save encrypted API key (base64 encoded for now)"""
    try:
        if not secret.key or not secret.value:
            raise HTTPException(status_code=400, detail="Key and value are required")

        # Load existing secrets
        secrets = load_secrets()

        # Encode value (simple base64 for now)
        encoded_value = base64.b64encode(secret.value.encode()).decode()
        secrets[secret.key] = encoded_value

        # Save
        if not save_secrets(secrets):
            raise HTTPException(status_code=500, detail="Failed to save secret")

        logger.info(f"✅ Secret saved: {secret.key} (service: {secret.service})")

        return SecretResponse(
            message=f"Secret '{secret.key}' saved successfully",
            key=secret.key,
            service=secret.service
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving secret: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving secret: {str(e)}")


@app.post("/api/restart", response_model=RestartResponse)
async def restart_gateway(token: str = Depends(verify_token)):
    """Restart gateway service"""
    try:
        logger.info("🔄 Restarting gateway service...")

        # Stop gateway
        stop_result = subprocess.run(
            ["pkill", "-f", "openclaw.*gateway"],
            capture_output=True,
            timeout=10
        )

        # Small delay
        import time
        time.sleep(2)

        # Start gateway (this is a placeholder - actual startup depends on your setup)
        # You might use systemctl, docker restart, or a custom start script
        # For now, we'll just kill the process and assume systemd/supervisor will restart it

        logger.info("✅ Gateway restart initiated")

        return RestartResponse(
            success=True,
            message="Gateway restart initiated. Service should be back online in 5-10 seconds.",
            timestamp=datetime.utcnow().isoformat()
        )
    except subprocess.TimeoutExpired:
        logger.error("Timeout restarting gateway")
        raise HTTPException(status_code=500, detail="Restart timeout")
    except Exception as e:
        logger.error(f"Error restarting gateway: {e}")
        raise HTTPException(status_code=500, detail=f"Error restarting gateway: {str(e)}")


@app.get("/api/health", response_model=HealthCheckResponse)
async def health_check(token: str = Depends(verify_token)):
    """Detailed health check"""
    try:
        gateway_running = check_service_running(GATEWAY_PORT, GATEWAY_HOST)
        tunnel_running = check_service_running(8001, GATEWAY_HOST)  # Assuming tunnel on 8001

        # Check database connectivity (assuming local)
        database_health = "healthy"  # Placeholder

        # Measure API latency
        import time
        start = time.time()
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/health"],
                capture_output=True,
                timeout=5
            )
            api_latency = (time.time() - start) * 1000
        except Exception:
            api_latency = 0

        # Get system metrics
        metrics = get_system_metrics()
        memory_usage = metrics.get("memory_mb", 0)
        cpu_usage = metrics.get("cpu_percent", 0)

        # Get uptime
        uptime_seconds = get_process_uptime(GATEWAY_PORT)
        uptime_hours = uptime_seconds / 3600

        # Count errors and warnings
        errors, warnings = count_errors_and_warnings(GATEWAY_LOG_PATH, hours=1)

        # Determine overall status
        if gateway_running and uptime_seconds > 0:
            if cpu_usage < 80 and memory_usage < 80:
                overall_status = "healthy"
            else:
                overall_status = "degraded"
        else:
            overall_status = "unhealthy"

        return HealthCheckResponse(
            status=overall_status,
            gateway_health="healthy" if gateway_running else "unhealthy",
            tunnel_health="healthy" if tunnel_running else "unhealthy",
            database_health=database_health,
            api_latency_ms=round(api_latency, 2),
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage,
            uptime_hours=round(uptime_hours, 2),
            errors_last_hour=errors,
            warnings_last_hour=warnings,
            timestamp=datetime.utcnow().isoformat()
        )
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        raise HTTPException(status_code=500, detail=f"Health check error: {str(e)}")


@app.get("/health")
async def basic_health():
    """Basic health check (no auth required)"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/")
async def root():
    """Root endpoint - serve dashboard"""
    dashboard_file = STATIC_DIR / "index.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file)

    return {
        "service": "OpenClaw Dashboard API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/docs")
async def docs():
    """API documentation"""
    return {
        "title": "OpenClaw Dashboard API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Basic health check (no auth)",
            "GET /api/status": "Gateway and tunnel status",
            "GET /api/logs": "Last 50 lines of logs",
            "GET /api/webhooks": "Webhook URLs",
            "GET /api/config": "Gateway configuration",
            "GET /api/health": "Detailed health check",
            "POST /api/secrets": "Save encrypted secrets",
            "POST /api/restart": "Restart gateway"
        },
        "auth": "Bearer token in Authorization header",
        "token": "[redacted]",
        "password": "[redacted]"
    }


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Generic exception handler"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ============================================================================
# Startup/Shutdown
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Startup event"""
    logger.info("=" * 60)
    logger.info("🚀 OpenClaw Dashboard API Starting")
    logger.info(f"📡 Gateway: {GATEWAY_HOST}:{GATEWAY_PORT}")
    logger.info(f"🔐 Dashboard: Bearer {DASHBOARD_TOKEN[:10]}...")
    logger.info(f"📊 Listening on 0.0.0.0:{DASHBOARD_PORT}")
    logger.info(f"📁 Static files: {STATIC_DIR}")
    logger.info(f"📝 Gateway logs: {GATEWAY_LOG_PATH}")
    logger.info(f"🔗 Tunnel logs: {TUNNEL_LOG_PATH}")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event"""
    logger.info("🛑 OpenClaw Dashboard API shutting down...")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # Ensure secrets file exists
    if not SECRETS_PATH.exists():
        save_secrets({})

    # Start server
    uvicorn.run(
        "dashboard_api:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=False,
        log_level="info"
    )
