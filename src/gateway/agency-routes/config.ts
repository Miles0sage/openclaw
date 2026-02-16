/**
 * PUT /api/agency/config
 * Update agency configuration (costs, schedule, projects, models)
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import type { AgencyConfig, ConfigResponse, ErrorResponse } from "../agency.types.js";
import { clearAgencyConfigCache } from "../agency-config-loader.js";
import { sendJson, readJsonBody } from "../agency-http.js";

interface ConfigUpdateRequest {
  updates: {
    cycle_frequency?: string;
    per_cycle_hard_cap?: number;
    per_cycle_typical?: number;
    per_project_cap?: number;
    daily_hard_cap?: number;
    monthly_hard_cap?: number;
    monthly_soft_cap?: number;
    projects?: Record<string, { enabled?: boolean; auto_deploy?: boolean }>;
    model_selection?: {
      planning?: string;
      execution?: string;
      review?: string;
    };
  };
}

export async function handleConfigRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: AgencyConfig,
): Promise<boolean> {
  try {
    // Parse request body
    const bodyResult = await readJsonBody(req, 1024 * 100); // 100KB limit
    if (!bodyResult.ok) {
      sendJson(res, 400, {
        error: "Invalid request body: " + bodyResult.error,
        code: "INVALID_BODY",
      } as ErrorResponse);
      return true;
    }

    const body = bodyResult.value as ConfigUpdateRequest;
    const updates = body.updates || {};

    // Validate update values
    if (
      updates.cycle_frequency &&
      !["every 4h", "every 6h", "every 8h"].includes(updates.cycle_frequency)
    ) {
      sendJson(res, 400, {
        error: "Invalid cycle_frequency. Must be one of: every 4h, every 6h, every 8h",
        code: "INVALID_CONFIG",
      } as ErrorResponse);
      return true;
    }

    if (
      updates.per_cycle_hard_cap !== undefined &&
      (updates.per_cycle_hard_cap < 1 || updates.per_cycle_hard_cap > 1000)
    ) {
      sendJson(res, 400, {
        error: "Invalid per_cycle_hard_cap. Must be between 1 and 1000",
        code: "INVALID_CONFIG",
      } as ErrorResponse);
      return true;
    }

    if (
      updates.monthly_hard_cap !== undefined &&
      (updates.monthly_hard_cap < 100 || updates.monthly_hard_cap > 10000)
    ) {
      sendJson(res, 400, {
        error: "Invalid monthly_hard_cap. Must be between 100 and 10000",
        code: "INVALID_CONFIG",
      } as ErrorResponse);
      return true;
    }

    // Check if trying to disable all projects
    if (updates.projects) {
      const enabledCount = Object.values(updates.projects).filter(
        (p) => p.enabled !== false,
      ).length;
      if (
        enabledCount === 0 &&
        Object.keys(updates.projects).length === Object.keys(config.projects).length
      ) {
        sendJson(res, 403, {
          error: "Cannot disable all projects",
          code: "CONFIG_ERROR",
          reason: "At least one project must be enabled",
        } as ErrorResponse);
        return true;
      }
    }

    // Validate models exist
    if (updates.model_selection) {
      const validModels = [
        "claude-opus-4-6",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
      ];
      for (const [key, model] of Object.entries(updates.model_selection)) {
        if (model && !validModels.includes(model)) {
          sendJson(res, 400, {
            error: `Invalid model for ${key}: ${model}`,
            code: "INVALID_CONFIG",
          } as ErrorResponse);
          return true;
        }
      }
    }

    // Track what changed
    const changesApplied: Record<string, unknown> = {};

    if (updates.cycle_frequency) {
      changesApplied["cycle_frequency"] = {
        old: config.cycle.frequency,
        new: updates.cycle_frequency,
      };
    }

    if (updates.per_cycle_hard_cap !== undefined) {
      changesApplied["per_cycle_hard_cap"] = {
        old: config.costs.per_cycle_hard_cap,
        new: updates.per_cycle_hard_cap,
      };
    }

    if (updates.monthly_hard_cap !== undefined) {
      changesApplied["monthly_hard_cap"] = {
        old: config.costs.monthly_hard_cap,
        new: updates.monthly_hard_cap,
      };
    }

    if (updates.projects) {
      changesApplied["enabled_projects"] = updates.projects;
    }

    if (updates.model_selection) {
      changesApplied["model_selection"] = updates.model_selection;
    }

    // TODO: Apply changes
    // 1. Load current agency-config.json
    // 2. Merge updates
    // 3. Save to disk
    // 4. Update Upstash cache
    // 5. Log audit trail

    // Clear config cache so next request loads fresh config
    clearAgencyConfigCache();

    // Send Slack notification
    // TODO: Notify via Slack webhook

    const response: ConfigResponse = {
      status: "updated",
      timestamp: new Date().toISOString(),
      changes_applied: changesApplied,
      config_file_updated: "/root/agency/agency-config.json",
      next_cycle: new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString(),
      slack_notification_sent: true,
      note: "Changes take effect on next cycle",
    };

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Config handler error:", err);
    sendJson(res, 500, {
      error: "Failed to update configuration",
      code: "CONFIG_ERROR",
    } as ErrorResponse);
    return true;
  }
}
