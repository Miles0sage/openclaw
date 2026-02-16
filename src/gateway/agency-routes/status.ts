/**
 * GET /api/agency/status
 * Check the status of a running or completed cycle
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import type { AgencyConfig, StatusResponse, ErrorResponse } from "../agency.types.js";
import { sendJson, getQueryParam } from "../agency-http.js";

export async function handleStatusRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
  url: URL,
): Promise<boolean> {
  try {
    // Get cycle_id from query params
    const cycleId = getQueryParam(url, "cycle_id");
    if (!cycleId) {
      sendJson(res, 400, {
        error: "Missing required parameter: cycle_id",
        code: "MISSING_PARAM",
      } as ErrorResponse);
      return true;
    }

    // Query Redis for cycle status
    // TODO: Fetch from Redis: agency:cycles:{cycleId}:status
    const cycleData = {
      cycle_id: cycleId,
      status: "execution_in_progress",
      phase: "execution",
      progress: {
        planning: { completed: 6, total: 6, status: "✅ done" },
        execution: { completed: 3, total: 6, status: "🔄 in progress" },
        review: { completed: 0, total: 6, status: "⏳ queued" },
      },
      projects: {
        "barber-crm": {
          status: "executing",
          plan_generated: new Date().toISOString(),
          plan_file: "https://github.com/Miles0sage/Barber-CRM/commits/...",
          test_status: "running",
        },
        "delhi-palace": {
          status: "executing",
          plan_generated: new Date().toISOString(),
          plan_file: "https://github.com/Miles0sage/Delhi-Palce-/commits/...",
          test_status: "running",
        },
        "concrete-canoe": {
          status: "planning_done",
          plan_generated: new Date().toISOString(),
          plan_file: "https://github.com/Miles0sage/concrete-canoe-project2026/commits/...",
        },
        openclaw: {
          status: "planning_done",
          plan_generated: new Date().toISOString(),
        },
        "prestress-calc": {
          status: "planning_done",
          plan_generated: new Date().toISOString(),
        },
        moltbot: {
          status: "planning_done",
          plan_generated: new Date().toISOString(),
        },
      },
      costs_so_far: {
        planning: "$3.00",
        execution: "$0.15",
        total: "$3.15",
      },
      eta_completion: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    };

    const response: StatusResponse = cycleData as StatusResponse;

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Status handler error:", err);
    sendJson(res, 500, {
      error: "Failed to retrieve cycle status",
      code: "STATUS_ERROR",
    } as ErrorResponse);
    return true;
  }
}
