/**
 * POST /api/agency/trigger
 * Start a new agency cycle (planning + execution + review for all or specified projects)
 */

import type { IncomingMessage, ServerResponse } from "node:http";
import type { AgencyConfig, TriggerResponse, ErrorResponse } from "../agency.types.js";
import { validateProjects, getEnabledProjects } from "../agency-config-loader.js";
import { sendJson, readJsonBody, getQueryParam } from "../agency-http.js";

interface TriggerRequest {
  projects?: string[]; // Optional: specific projects to run
  force?: boolean; // Optional: skip change detection
}

export async function handleTriggerRequest(
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

    const body = bodyResult.value as TriggerRequest;
    const requestedProjects = body.projects || [];
    const force = body.force ?? false;

    // Determine which projects to run
    let projectsToRun =
      requestedProjects.length > 0 ? requestedProjects : config.projects.map((p) => p.id);

    // Validate requested projects exist
    if (requestedProjects.length > 0) {
      const validation = validateProjects(config, requestedProjects);
      if (!validation.valid) {
        sendJson(res, 400, {
          error: `Invalid projects: ${validation.invalidProjects.join(", ")}`,
          code: "INVALID_PROJECT",
          valid_projects: config.projects.map((p) => p.id),
        } as ErrorResponse);
        return true;
      }
    }

    // Check if a cycle is already running
    const cycleKey = `agency:cycles:current`;
    // TODO: Check Redis for active cycle
    // For now, assume we can proceed

    // Generate cycle ID: YYYY-MM-DD-NNN
    const cycleId = generateCycleId();

    // Record cycle in Redis
    // TODO: Store cycle metadata in Redis
    const cycleMetadata = {
      cycle_id: cycleId,
      status: "planning_started",
      projects_queued: projectsToRun.length,
      created_at: new Date().toISOString(),
      force_skip_change_detection: force,
    };

    // Enqueue planning jobs for each project
    // TODO: Enqueue to agency:planning queue in Upstash
    for (const projectId of projectsToRun) {
      const planningJob = {
        cycle_id: cycleId,
        project_id: projectId,
        repo_path: config.projects.find((p) => p.id === projectId)?.local_path,
        models: "opus",
        timestamp: new Date().toISOString(),
      };
      // TODO: client.lpush("agency:planning", JSON.stringify(planningJob))
    }

    // Send Slack notification
    // TODO: Notify via Slack webhook

    // Return response
    const response: TriggerResponse = {
      cycle_id: cycleId,
      status: "planning_started",
      projects_queued: projectsToRun.length,
      estimated_cost: "$3.80",
      estimated_time_minutes: 45,
      timestamp: new Date().toISOString(),
      job_urls: {
        planning_queue: "https://console.upstash.com/redis/...",
        tracking_url: `/api/agency/status?cycle_id=${cycleId}`,
      },
    };

    sendJson(res, 200, response);
    return true;
  } catch (err) {
    console.error("Trigger handler error:", err);
    sendJson(res, 500, {
      error: "Failed to start cycle",
      code: "TRIGGER_ERROR",
    } as ErrorResponse);
    return true;
  }
}

/**
 * Generate a cycle ID in format: YYYY-MM-DD-NNN
 */
function generateCycleId(): string {
  const now = new Date();
  const dateStr = now.toISOString().split("T")[0]; // YYYY-MM-DD
  const randomNum = String(Math.floor(Math.random() * 1000)).padStart(3, "0"); // NNN
  return `${dateStr}-${randomNum}`;
}
