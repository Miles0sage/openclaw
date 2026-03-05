"""Health, version, dashboard, and static page endpoints."""

import os
import json
import time
import uuid
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from routers.shared import CONFIG, metrics, BASE_DIR

logger = logging.getLogger("openclaw.routers.health")

router = APIRouter()


# ---------------------------------------------------------------------------
# Landing / static pages
# ---------------------------------------------------------------------------

@router.get("/")
async def root():
    """Serve the OpenClaw sales landing page."""
    try:
        sales_path = "/root/openclaw/static/sales/index.html"
        with open(sales_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return JSONResponse({
            "name": "OpenClaw Gateway",
            "version": "2.0.0",
            "status": "online",
            "agents": len(CONFIG.get("agents", {})),
            "protocol": "OpenClaw v1",
            "model_config": {
                agent: {
                    "provider": cfg.get("apiProvider"),
                    "model": cfg.get("model")
                }
                for agent, cfg in CONFIG.get("agents", {}).items()
            }
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/sales")
async def sales_page():
    """Serve the OpenClaw sales landing page (alias)."""
    try:
        sales_path = "/root/openclaw/static/sales/index.html"
        with open(sales_path, "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Sales page not found</h1>", status_code=404)


@router.get("/visionclaw")
async def visionclaw_page():
    """Serve the VisionClaw open-source smart glasses page."""
    try:
        with open("/root/openclaw/static/visionclaw/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Page not found</h1>", status_code=404)


@router.get("/nightowl")
async def nightowl_page():
    """Serve the NightOwl Security landing page."""
    try:
        with open("/root/openclaw/static/nightowl/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Page not found</h1>", status_code=404)


@router.post("/api/security/scan")
async def security_scan_api(request: Request):
    """Accept a security scan request from NightOwl website."""
    try:
        data = await request.json()
        target_url = data.get("url", "").strip()
        email = data.get("email", "").strip()
        scan_type = data.get("scan_type", "quick")

        if not target_url or not email:
            return JSONResponse({"error": "URL and email are required"}, status_code=400)

        scan_id = f"scan-{uuid.uuid4().hex[:12]}"

        scan_log = {
            "scan_id": scan_id,
            "target": target_url,
            "email": email,
            "scan_type": scan_type,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        os.makedirs("/root/openclaw/data/scans", exist_ok=True)
        with open("/root/openclaw/data/scans/scans.jsonl", "a") as f:
            f.write(json.dumps(scan_log) + "\n")

        try:
            tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if tg_token:
                msg = f"🦉 NightOwl scan request!\n\nTarget: {target_url}\nType: {scan_type}\nEmail: {email}\nID: {scan_id}"
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": "8475962905", "text": msg}
                    )
        except Exception:
            pass

        try:
            from job_manager import add_job
            add_job({
                "project": "nightowl",
                "task": f"Run {scan_type} security scan on {target_url} and email results to {email}. Scan ID: {scan_id}",
                "priority": "P1",
            })
        except Exception:
            pass

        return JSONResponse({
            "scan_id": scan_id,
            "status": "queued",
            "message": f"Scan queued. Results will be emailed to {email}.",
        })

    except Exception as e:
        logger.error(f"Security scan API error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/terms")
async def terms_page():
    """Serve the Terms of Service page."""
    try:
        terms_path = "/root/openclaw/landing/terms.html"
        with open(terms_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Terms of Service not found</h1><p>terms.html is missing.</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading terms</h1><p>{str(e)}</p>",
            status_code=500
        )


@router.get("/test-version")
async def test_version():
    """Test endpoint to verify deployed version"""
    return {
        "status": "deployed",
        "timestamp": datetime.now().isoformat(),
        "auth_middleware": "active_with_exemptions",
        "exempt_paths": ["/", "/health", "/telegram/webhook", "/slack/events"],
        "version": "fixed-2026-02-18"
    }


@router.post("/api/admin/log-level")
async def set_log_level(request: Request):
    body = await request.json()
    level = body.get("level", "INFO").upper()
    numeric = getattr(logging, level, None)
    if numeric is None:
        raise HTTPException(400, detail=f"Invalid log level: {level}")
    logging.getLogger().setLevel(numeric)
    return {"level": level, "ok": True}


@router.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "operational",
        "gateway": "OpenClaw v4.1",
        "version": "4.1.0",
        "agents_active": len(CONFIG.get("agents", {})),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/api/health")
async def api_health():
    """System health endpoint — used by monitoring, dashboards, and probes."""
    import psutil
    process = psutil.Process()
    uptime_seconds = time.time() - process.create_time()
    return {
        "status": "operational",
        "version": "4.1.0",
        "uptime_seconds": int(uptime_seconds),
        "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
        "agents_configured": len(CONFIG.get("agents", {})),
        "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/api/ping")
async def api_ping():
    """Simple ping endpoint to check API responsiveness"""
    return {"pong": True, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/api/version")
async def api_get_version():
    """Get API version and system information"""
    return {"version": "4.2.0", "name": "openclaw", "engine": "autonomous_runner"}


@router.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint (no auth required for K8s scraping)"""
    return PlainTextResponse(metrics.get_prometheus_metrics())


@router.get("/test-exempt")
async def test_exempt():
    """Test endpoint to verify auth exemptions work (no auth required)"""
    return {"message": "✅ Auth exemption working!", "path": "/test-exempt"}


# ---------------------------------------------------------------------------
# Dashboard pages
# ---------------------------------------------------------------------------

@router.get("/dashboard.html")
async def dashboard(request: Request):
    """Serve HTML dashboard (no auth required)"""
    try:
        dashboard_path = "/root/openclaw/dashboard.html"
        with open(dashboard_path, 'r') as f:
            html_content = f.read()
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return HTMLResponse(content=html_content)
        return HTMLResponse(content="Method not allowed", status_code=405)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard.html is missing</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading dashboard</h1><p>{str(e)}</p>",
            status_code=500
        )


@router.get("/prestress/{page}")
async def prestress_course(page: str):
    """Serve prestress course pages (no auth)"""
    try:
        path = f"/root/prestress-course/{page}.html"
        with open(path, 'r') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content=f"<h1>Page '{page}' not found</h1>", status_code=404)


@router.get("/intake")
async def intake_form():
    """Serve the client intake form page (no auth)"""
    try:
        intake_path = "/root/openclaw/static/sales/intake.html"
        with open(intake_path, 'r') as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Intake form not found</h1>", status_code=404)
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading intake form</h1><p>{str(e)}</p>", status_code=500)


@router.get("/monitoring")
async def monitoring_dashboard(request: Request):
    """Serve the main dashboard (consolidated from static/dashboard.html)"""
    try:
        dashboard_path = os.path.join(BASE_DIR, "dashboard.html")
        with open(dashboard_path, 'r') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard.html is missing</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading dashboard</h1><p>{e}</p>", status_code=500)


@router.get("/secrets")
async def secrets_dashboard():
    """Serve the secrets manager dashboard"""
    html_path = os.path.join(BASE_DIR, "dashboard_secrets.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Secrets dashboard not found</h1>", status_code=404)


@router.get("/metrics-dashboard")
async def metrics_dashboard():
    """Serve the metrics dashboard"""
    html_path = os.path.join(BASE_DIR, "dashboard_metrics.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Metrics dashboard not found</h1>", status_code=404)


@router.get("/mobile")
async def mobile_dashboard():
    """Serve the mobile dashboard"""
    html_path = os.path.join(BASE_DIR, "dashboard_mobile.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Mobile dashboard not found</h1>", status_code=404)
