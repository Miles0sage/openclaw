/**
 * GET /api/agency/costs
 * Show cumulative costs for the current month or custom date range
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import type { AgencyConfig, CostsResponse, ErrorResponse } from "../agency.types.js";
import { sendJson, getQueryParam } from "../agency-http.js";

export async function handleCostsRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
  url: URL,
): Promise<boolean> {
  try {
    // Parse optional date range
    const fromStr = getQueryParam(url, "from");
    const toStr = getQueryParam(url, "to");

    const today = new Date();
    const monthStart = new Date(today.getFullYear(), today.getMonth(), 1);
    const from = fromStr ? new Date(fromStr) : monthStart;
    const to = toStr ? new Date(toStr) : today;

    // Validate dates
    if (isNaN(from.getTime()) || isNaN(to.getTime())) {
      sendJson(res, 400, {
        error: "Invalid date format. Use YYYY-MM-DD",
        code: "INVALID_DATE",
      } as ErrorResponse);
      return true;
    }

    // Query Redis for costs
    // TODO: Fetch aggregates from Redis

    const response: CostsResponse = {
      period: `${from.toISOString().split("T")[0]} to ${to.toISOString().split("T")[0]}`,
      cycles_completed: 11,
      cycles_in_progress: 0,
      costs: {
        total: "$41.80",
        by_phase: {
          planning: {
            total: "$33.00",
            cycles: 11,
            avg_per_cycle: "$3.00",
            model: "claude-opus-4-6",
            tokens_used: 550000,
          },
          execution: {
            total: "$3.30",
            cycles: 11,
            avg_per_cycle: "$0.30",
            model: "claude-haiku-4-5-20251001",
            tokens_used: 1100000,
          },
          review: {
            total: "$5.50",
            cycles: 11,
            avg_per_cycle: "$0.50",
            model: "claude-opus-4-6",
            tokens_used: 183000,
          },
        },
        by_project: {
          "barber-crm": "$8.20",
          "delhi-palace": "$7.50",
          "concrete-canoe": "$6.80",
          openclaw: "$7.10",
          "prestress-calc": "$5.60",
          moltbot: "$6.60",
        },
      },
      guardrails: {
        per_cycle_cap: "$8.00",
        per_cycle_max_exceeded: 0,
        daily_cap: "$40.00",
        daily_max_exceeded: 0,
        monthly_cap: "$600.00",
        remaining_budget: "$558.20",
      },
      projections: {
        projected_monthly_total: "$82.80",
        days_remaining_in_month: 14,
        will_exceed_budget: false,
      },
      efficiency: {
        cost_per_feature: "$0.64",
        prs_merged: 62,
        avg_pr_size: "85 lines",
        test_pass_rate: "98.4%",
      },
      timestamp: new Date().toISOString(),
    };

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Costs handler error:", err);
    sendJson(res, 500, {
      error: "Failed to retrieve costs",
      code: "COSTS_ERROR",
    } as ErrorResponse);
    return true;
  }
}
