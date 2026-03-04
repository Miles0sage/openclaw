# OpenClaw Backend Implementation Specification

## AI Integration Technical Roadmap for Backend Team

**Date**: March 4, 2026
**Scope**: `src/app/api/**`, `src/lib/**`, `src/middleware.ts`
**Priority**: Critical (MCP 1.0) → High (Handoff Protocols, Extended Tool Use)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   NextRequest/Response                  │
├─────────────────────────────────────────────────────────┤
│ src/app/api/**                                          │
│ ├── /agents/handoff (NEW)                              │
│ ├── /agents/tool-use (NEW)                             │
│ ├── /memory/context (NEW)                              │
│ ├── /benchmark/metrics (NEW)                           │
│ └── /mcp/* (MIGRATE TO 1.0)                            │
├─────────────────────────────────────────────────────────┤
│ src/middleware.ts                                       │
│ ├── MCP 1.0 routing layer                              │
│ ├── Context propagation                                │
│ └── Agent validation                                   │
├─────────────────────────────────────────────────────────┤
│ src/lib/**                                              │
│ ├── mcp-client.ts (UPDATE)                             │
│ ├── claude-client.ts (UPDATE)                          │
│ ├── agent-handoff.ts (NEW)                             │
│ ├── memory-layer.ts (NEW)                              │
│ └── benchmark-collector.ts (NEW)                       │
└─────────────────────────────────────────────────────────┘
```

---

## 1. MCP 1.0 Migration

### Files to Update

#### `src/lib/mcp-client.ts` (PRIORITY: CRITICAL)

**Current**: MCP pre-1.0 client
**Target**: MCP 1.0 stable compatible

**Key Changes**:

```typescript
// src/lib/mcp-client.ts

import { Client, ServerCapabilities } from "@modelcontextprotocol/sdk/client/index";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio";

// CHANGE 1: Update initialization to MCP 1.0
export class MCPClientV1 {
  private client: Client;
  private capabilities: ServerCapabilities;

  async initialize(serverPath: string, env?: Record<string, string>) {
    const transport = new StdioClientTransport({
      command: serverPath,
      env: env || process.env,
    });

    this.client = new Client(
      {
        name: "openclaw-agent",
        version: "1.0.0",
      },
      {
        capabilities: {
          // MCP 1.0: Explicit capability declaration
          tools: { listChanged: true },
          resources: { listChanged: true },
          sampling: {},
        },
      },
    );

    await this.client.connect(transport);
    this.capabilities = await this.client.getServerCapabilities();
  }

  // CHANGE 2: New routing method (breaking change in MCP 1.0)
  async routeMessage(message: MCPMessage): Promise<MCPResponse> {
    const { resourceUri, toolName, samplingMessage } = message;

    // MCP 1.0 uses explicit routing instead of magic method names
    if (resourceUri) {
      return await this.client.read({ uri: resourceUri });
    } else if (toolName) {
      return await this.client.callTool({ name: toolName, arguments: {} });
    } else if (samplingMessage) {
      return await this.client.createMessage(samplingMessage);
    }
  }

  // CHANGE 3: Add breaking change handling
  async handleDeprecatedMethods(oldCall: string): Promise<void> {
    console.warn(`[MCP 1.0] Deprecated method called: ${oldCall}`);
    // Log for audit trail, then route to new method
  }

  async disconnect() {
    await this.client.close();
  }
}
```

**Migration Checklist**:

- [ ] Update MCP npm package to v1.0.0+
- [ ] Replace old client initialization
- [ ] Update all tool invocation calls
- [ ] Add compatibility layer for deprecated methods (temporary)
- [ ] Audit all agent-to-MCP communication paths
- [ ] Run comprehensive integration tests

**Breaking Changes to Handle**:

1. Tool invocation syntax changed
2. Resource URI format updated
3. Error message structure modified
4. Capability negotiation is now explicit

---

#### `src/middleware.ts` (MCP 1.0 Routing)

**Add**:

```typescript
// src/middleware.ts

import { NextRequest, NextResponse } from "next/server";
import { MCPClientV1 } from "./lib/mcp-client";

const mcpClient = new MCPClientV1();

export async function middleware(request: NextRequest) {
  const path = request.nextUrl.pathname;

  // NEW: MCP 1.0 routing
  if (path.startsWith("/api/mcp/")) {
    const mcpPath = path.replace("/api/mcp/", "");

    try {
      // MCP 1.0: Explicit routing
      const response = await mcpClient.routeMessage({
        resourceUri: mcpPath,
        toolName: request.headers.get("x-tool-name") || undefined,
      });

      return NextResponse.json(response);
    } catch (error) {
      console.error("[MCP 1.0] Routing error:", error);
      return NextResponse.json(
        { error: "MCP routing failed", details: String(error) },
        { status: 500 },
      );
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/api/mcp/:path*"],
};
```

---

### Testing Strategy

**File**: `src/__tests__/mcp-migration.test.ts`

```typescript
describe("MCP 1.0 Migration", () => {
  let mcpClient: MCPClientV1;

  beforeAll(async () => {
    mcpClient = new MCPClientV1();
    // Initialize with test server
  });

  describe("Breaking Changes", () => {
    test("should handle tool invocation with new syntax", async () => {
      const result = await mcpClient.callTool({
        name: "test_tool",
        arguments: { param: "value" },
      });
      expect(result).toBeDefined();
    });

    test("should route resources by URI", async () => {
      const result = await mcpClient.read({
        uri: "mcp://resource/path",
      });
      expect(result).toBeDefined();
    });

    test("should maintain backward compatibility via adapter", async () => {
      // Old syntax should be redirected to new syntax
      const result = await mcpClient.handleDeprecatedMethods("oldMethod");
      expect(result).toBeDefined();
    });
  });
});
```

---

## 2. Deterministic Agent Handoff Protocols

### New File: `src/lib/agent-handoff.ts`

```typescript
// src/lib/agent-handoff.ts

import { createHash } from "crypto";

export interface HandoffContext {
  agent_id: string;
  session_id: string;
  task_id: string;
  context_data: Record<string, any>;
  metadata: Record<string, string>;
  timestamp: number;
}

export interface HandoffValidation {
  context_checksum: string;
  validation_rules: ValidationRule[];
  fallback_agent_id: string;
  retry_count: number;
  max_retries: number;
}

export interface ValidationRule {
  name: string;
  check: (context: HandoffContext) => boolean;
  error_message: string;
}

export class DeterministicHandoffProtocol {
  private validationRules: Map<string, ValidationRule[]> = new Map();

  /**
   * Compute deterministic checksum of context
   * Ensures context integrity across handoff
   */
  computeContextChecksum(context: HandoffContext): string {
    const contextStr = JSON.stringify(context, Object.keys(context).sort());
    return createHash("sha256").update(contextStr).digest("hex");
  }

  /**
   * Register validation rules for agent pair
   */
  registerValidationRules(sourceAgent: string, targetAgent: string, rules: ValidationRule[]): void {
    const key = `${sourceAgent}->${targetAgent}`;
    this.validationRules.set(key, rules);
  }

  /**
   * Validate handoff before executing
   * Returns detailed error information if validation fails
   */
  async validateHandoff(
    sourceAgent: string,
    targetAgent: string,
    context: HandoffContext,
  ): Promise<{ valid: boolean; errors: string[] }> {
    const rules = this.validationRules.get(`${sourceAgent}->${targetAgent}`) || [];
    const errors: string[] = [];

    // Standard validation rules (always applied)
    const standardRules = [
      {
        name: "session_exists",
        check: (ctx: HandoffContext) => !!ctx.session_id,
        error: "session_id is required",
      },
      {
        name: "task_exists",
        check: (ctx: HandoffContext) => !!ctx.task_id,
        error: "task_id is required",
      },
      {
        name: "context_not_empty",
        check: (ctx: HandoffContext) => Object.keys(ctx.context_data).length > 0,
        error: "context_data cannot be empty",
      },
    ];

    // Run all validation rules
    const allRules = [...standardRules, ...rules];
    for (const rule of allRules) {
      if (!rule.check(context)) {
        errors.push(rule.error_message || rule.error);
      }
    }

    return {
      valid: errors.length === 0,
      errors,
    };
  }

  /**
   * Execute deterministic handoff
   * Guarantees context preservation or explicit failure
   */
  async executeHandoff(
    sourceAgent: string,
    targetAgent: string,
    context: HandoffContext,
    validation: HandoffValidation,
  ): Promise<HandoffResult> {
    const startTime = Date.now();

    // Step 1: Validate handoff
    const validation_result = await this.validateHandoff(sourceAgent, targetAgent, context);

    if (!validation_result.valid) {
      return {
        success: false,
        error: "Validation failed",
        details: validation_result.errors,
        duration_ms: Date.now() - startTime,
      };
    }

    // Step 2: Compute context checksum
    const context_checksum = this.computeContextChecksum(context);
    if (context_checksum !== validation.context_checksum) {
      return {
        success: false,
        error: "Context checksum mismatch",
        details: ["Context was modified during handoff preparation"],
        duration_ms: Date.now() - startTime,
      };
    }

    // Step 3: Execute handoff with retry logic
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= validation.max_retries; attempt++) {
      try {
        const result = await this._performHandoff(sourceAgent, targetAgent, context);

        return {
          success: true,
          target_agent: targetAgent,
          context_checksum,
          attempt,
          duration_ms: Date.now() - startTime,
        };
      } catch (error) {
        lastError = error as Error;
        console.error(`[Handoff] Attempt ${attempt + 1} failed:`, lastError.message);

        if (attempt < validation.max_retries) {
          // Exponential backoff
          const delay = Math.pow(2, attempt) * 100;
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
    }

    // Step 4: Fallback to alternate agent
    if (validation.fallback_agent_id) {
      console.warn(`[Handoff] Falling back from ${targetAgent} to ${validation.fallback_agent_id}`);
      return await this.executeHandoff(
        sourceAgent,
        validation.fallback_agent_id,
        context,
        { ...validation, fallback_agent_id: null }, // Prevent infinite recursion
      );
    }

    return {
      success: false,
      error: "Handoff failed after retries and fallback",
      details: [lastError?.message || "Unknown error"],
      duration_ms: Date.now() - startTime,
    };
  }

  private async _performHandoff(
    sourceAgent: string,
    targetAgent: string,
    context: HandoffContext,
  ): Promise<void> {
    // Implementation: Actually transfer control
    // This would call the target agent's initialization endpoint
    // and pass the context
    throw new Error("Not implemented"); // Override in subclass
  }
}

export interface HandoffResult {
  success: boolean;
  target_agent?: string;
  error?: string;
  details?: string[];
  context_checksum?: string;
  attempt?: number;
  duration_ms: number;
}
```

### New API Endpoint: `src/app/api/agents/handoff/route.ts`

```typescript
// src/app/api/agents/handoff/route.ts

import { NextRequest, NextResponse } from "next/server";
import { DeterministicHandoffProtocol } from "@/lib/agent-handoff";
import { requireAuth } from "@/lib/auth";

const handoffProtocol = new DeterministicHandoffProtocol();

// Register handoff validation rules
handoffProtocol.registerValidationRules("CodeGen-Pro", "CodeGen-Elite", [
  {
    name: "complexity_threshold",
    check: (ctx) => {
      const complexity = ctx.context_data.task_complexity || 0;
      return complexity > 5; // Only escalate complex tasks
    },
    error_message: "Task complexity too low for escalation to Elite",
  },
]);

export async function POST(request: NextRequest) {
  const auth = requireAuth();
  if (!auth.authorized) {
    return auth.response;
  }

  // Rate limit: 100 handoffs per minute
  if (!checkRateLimit(request.ip || "unknown", 100)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const body = await request.json();
    const { source_agent, target_agent, context, validation } = body;

    // Execute handoff
    const result = await handoffProtocol.executeHandoff(
      source_agent,
      target_agent,
      context,
      validation,
    );

    // Log handoff for audit trail
    console.log("[Handoff Result]", {
      source_agent,
      target_agent,
      success: result.success,
      duration_ms: result.duration_ms,
      attempt: result.attempt,
    });

    return NextResponse.json(result);
  } catch (error) {
    console.error("[Handoff] Unexpected error:", error);
    return NextResponse.json(
      { error: "Handoff execution failed", details: String(error) },
      { status: 500 },
    );
  }
}
```

---

## 3. Extended Tool Use Integration

### Update: `src/lib/claude-client.ts`

```typescript
// src/lib/claude-client.ts - Extended Tool Use Support

export interface ExtendedToolDefinition {
  name: string;
  description: string;
  input_schema: {
    type: "object";
    properties: Record<string, any>;
    required?: string[];
  };
  // NEW: Vision capabilities for code analysis
  vision?: {
    enabled: boolean;
    modes: AnalysisMode[];
  };
}

export type AnalysisMode =
  | "code_review"
  | "architecture_analysis"
  | "screenshot_analysis"
  | "diagram_analysis";

export class ClaudeClientV1 {
  private client: any; // Anthropic client
  private extendedTools: Map<string, ExtendedToolDefinition> = new Map();

  /**
   * Register tool with extended capabilities
   */
  registerExtendedTool(tool: ExtendedToolDefinition): void {
    this.extendedTools.set(tool.name, tool);
  }

  /**
   * Get all registered tools in Anthropic API format
   */
  getToolDefinitions(): any[] {
    return Array.from(this.extendedTools.values()).map((tool) => ({
      name: tool.name,
      description: tool.description,
      input_schema: tool.input_schema,
      // NEW: Vision configuration
      ...(tool.vision?.enabled && {
        vision_config: {
          supported_modes: tool.vision.modes,
        },
      }),
    }));
  }

  /**
   * Call Claude with extended tool use
   * Handles both text and vision-based tool calls
   */
  async invokeWithTools(
    messages: Array<{ role: string; content: string }>,
    model: string = "claude-opus-4-6",
  ): Promise<ToolUseResponse> {
    const response = await this.client.messages.create({
      model,
      max_tokens: 4096,
      tools: this.getToolDefinitions(),
      messages,
    });

    return {
      content: response.content,
      tool_use_blocks: response.content.filter((block: any) => block.type === "tool_use"),
      // NEW: Vision analysis results
      vision_results: response.content.filter((block: any) => block.type === "vision_analysis"),
    };
  }

  /**
   * Execute tool with vision support
   */
  async executeToolWithVision(
    toolName: string,
    parameters: Record<string, any>,
    imageData?: Buffer,
  ): Promise<any> {
    const tool = this.extendedTools.get(toolName);
    if (!tool) throw new Error(`Unknown tool: ${toolName}`);

    // If vision is needed and image provided
    if (tool.vision?.enabled && imageData) {
      const base64Image = imageData.toString("base64");
      return await this._executeVisionAnalysis(
        toolName,
        parameters,
        base64Image,
        tool.vision.modes,
      );
    }

    // Regular tool execution
    return await this._executeTool(toolName, parameters);
  }

  private async _executeVisionAnalysis(
    toolName: string,
    parameters: Record<string, any>,
    base64Image: string,
    modes: AnalysisMode[],
  ): Promise<any> {
    // Implementation: Execute tool with vision context
    throw new Error("Not implemented");
  }

  private async _executeTool(toolName: string, parameters: Record<string, any>): Promise<any> {
    // Implementation: Execute tool without vision
    throw new Error("Not implemented");
  }
}

export interface ToolUseResponse {
  content: any[];
  tool_use_blocks: Array<{
    type: "tool_use";
    name: string;
    input: Record<string, any>;
  }>;
  vision_results?: any[];
}
```

### Register Extended Tools

**File**: `src/lib/tool-registry.ts`

```typescript
// src/lib/tool-registry.ts

import { ClaudeClientV1, ExtendedToolDefinition } from "./claude-client";

export function registerCodeAnalysisTools(client: ClaudeClientV1): void {
  // Tool 1: Code Review with Vision
  client.registerExtendedTool({
    name: "review_code",
    description: "Review code with visual analysis of architecture",
    input_schema: {
      type: "object",
      properties: {
        file_path: { type: "string" },
        code_content: { type: "string" },
        analysis_depth: { enum: ["shallow", "comprehensive"] },
      },
      required: ["file_path", "code_content"],
    },
    vision: {
      enabled: true,
      modes: ["code_review", "architecture_analysis"],
    },
  });

  // Tool 2: Architecture Analysis
  client.registerExtendedTool({
    name: "analyze_architecture",
    description: "Analyze system architecture with visual diagrams",
    input_schema: {
      type: "object",
      properties: {
        system_name: { type: "string" },
        component_diagram: { type: "string" }, // Base64 image
      },
      required: ["system_name"],
    },
    vision: {
      enabled: true,
      modes: ["architecture_analysis", "diagram_analysis"],
    },
  });
}
```

---

## 4. New Distributed Memory Layer

### New File: `src/lib/memory-layer.ts`

```typescript
// src/lib/memory-layer.ts

import { createClient } from "@supabase/supabase-js";

export interface AgentContext {
  context_id: string;
  agent_id: string;
  session_id: string;
  task_id: string;
  data: Record<string, any>;
  created_at: number;
  updated_at: number;
  ttl: number; // seconds
  version: number;
}

export class DistributedMemoryLayer {
  private supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_KEY!);

  private fallback: Map<string, AgentContext> = new Map();

  /**
   * Store or update context in distributed memory
   */
  async storeContext(context: AgentContext): Promise<void> {
    try {
      const { error } = await this.supabase.from("agent_contexts").upsert(
        {
          context_id: context.context_id,
          agent_id: context.agent_id,
          session_id: context.session_id,
          data: context.data,
          ttl: context.ttl,
          version: context.version,
          updated_at: Date.now(),
        },
        { onConflict: "context_id" },
      );

      if (error) throw error;
    } catch (error) {
      console.error("[Memory] Supabase write failed, using fallback:", error);
      this.fallback.set(context.context_id, context);
    }
  }

  /**
   * Retrieve context from distributed memory
   */
  async getContext(contextId: string): Promise<AgentContext | null> {
    try {
      const { data, error } = await this.supabase
        .from("agent_contexts")
        .select("*")
        .eq("context_id", contextId)
        .single();

      if (error && error.code !== "PGRST116") throw error; // Ignore not-found
      return data as AgentContext | null;
    } catch (error) {
      console.error("[Memory] Supabase read failed, checking fallback:", error);
      return this.fallback.get(contextId) || null;
    }
  }

  /**
   * Share context across agent network
   */
  async shareContext(contextId: string, targetAgentIds: string[]): Promise<void> {
    const context = await this.getContext(contextId);
    if (!context) throw new Error(`Context not found: ${contextId}`);

    // Create context references for each target agent
    const sharePromises = targetAgentIds.map((agentId) =>
      this.supabase.from("context_shares").insert({
        source_context_id: contextId,
        target_agent_id: agentId,
        shared_at: Date.now(),
      }),
    );

    await Promise.all(sharePromises);
  }

  /**
   * Get all contexts accessible to an agent
   */
  async getAccessibleContexts(agentId: string): Promise<AgentContext[]> {
    const { data, error } = await this.supabase.from("agent_contexts").select("*")
      .or(`agent_id.eq.${agentId},context_id.in(
        select source_context_id from context_shares
        where target_agent_id = '${agentId}'
      )`);

    if (error) {
      console.error("[Memory] Query failed:", error);
      return Array.from(this.fallback.values()).filter((ctx) => ctx.agent_id === agentId);
    }

    return data as AgentContext[];
  }

  /**
   * Set TTL (time-to-live) for context auto-expiration
   */
  async setContextTTL(contextId: string, ttlSeconds: number): Promise<void> {
    const context = await this.getContext(contextId);
    if (!context) throw new Error(`Context not found: ${contextId}`);

    context.ttl = ttlSeconds;
    context.updated_at = Date.now();
    await this.storeContext(context);
  }
}
```

### Supabase Schema

**File**: `supabase/migrations/001_agent_memory.sql`

```sql
-- Distributed memory layer for agent contexts
CREATE TABLE IF NOT EXISTS agent_contexts (
  context_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id VARCHAR NOT NULL,
  session_id VARCHAR NOT NULL,
  task_id VARCHAR NOT NULL,
  data JSONB NOT NULL,
  ttl INTEGER DEFAULT 3600,
  version INTEGER DEFAULT 1,
  created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  updated_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  INDEX idx_agent_id (agent_id),
  INDEX idx_session_id (session_id)
);

-- Context sharing across agent network
CREATE TABLE IF NOT EXISTS context_shares (
  share_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_context_id UUID REFERENCES agent_contexts(context_id),
  target_agent_id VARCHAR NOT NULL,
  shared_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
  INDEX idx_target_agent (target_agent_id)
);

-- TTL cleanup job (scheduled)
CREATE OR REPLACE FUNCTION cleanup_expired_contexts()
RETURNS void AS $$
BEGIN
  DELETE FROM agent_contexts
  WHERE updated_at + (ttl * 1000) < EXTRACT(EPOCH FROM NOW())::BIGINT * 1000;
END;
$$ LANGUAGE plpgsql;
```

---

## 5. Benchmark Collection System

### New File: `src/lib/benchmark-collector.ts`

```typescript
// src/lib/benchmark-collector.ts

export interface BenchmarkMetric {
  metric_name: string;
  value: number;
  unit: string;
  timestamp: number;
  agent_id?: string;
  tags?: Record<string, string>;
}

export class BenchmarkCollector {
  private metrics: BenchmarkMetric[] = [];

  /**
   * Record tool invocation performance
   */
  recordToolInvocation(
    toolName: string,
    durationMs: number,
    success: boolean,
    agentId?: string,
  ): void {
    this.metrics.push({
      metric_name: "tool_invocation_duration",
      value: durationMs,
      unit: "ms",
      timestamp: Date.now(),
      agent_id: agentId,
      tags: {
        tool_name: toolName,
        success: success ? "true" : "false",
      },
    });
  }

  /**
   * Record handoff performance
   */
  recordHandoff(
    sourceAgent: string,
    targetAgent: string,
    durationMs: number,
    success: boolean,
  ): void {
    this.metrics.push({
      metric_name: "agent_handoff_duration",
      value: durationMs,
      unit: "ms",
      timestamp: Date.now(),
      agent_id: sourceAgent,
      tags: {
        source_agent: sourceAgent,
        target_agent: targetAgent,
        success: success ? "true" : "false",
      },
    });
  }

  /**
   * Record context propagation latency
   */
  recordContextPropagation(contextSize: number, durationMs: number, recipientCount: number): void {
    this.metrics.push({
      metric_name: "context_propagation_latency",
      value: durationMs,
      unit: "ms",
      timestamp: Date.now(),
      tags: {
        context_size_bytes: contextSize.toString(),
        recipient_count: recipientCount.toString(),
      },
    });
  }

  /**
   * Get metrics summary
   */
  getSummary(): Record<string, any> {
    const grouped = this.metrics.reduce(
      (acc, metric) => {
        if (!acc[metric.metric_name]) {
          acc[metric.metric_name] = [];
        }
        acc[metric.metric_name].push(metric.value);
        return acc;
      },
      {} as Record<string, number[]>,
    );

    return Object.entries(grouped).reduce(
      (acc, [name, values]) => {
        acc[name] = {
          count: values.length,
          avg: values.reduce((a, b) => a + b, 0) / values.length,
          min: Math.min(...values),
          max: Math.max(...values),
          p95: this._percentile(values, 95),
          p99: this._percentile(values, 99),
        };
        return acc;
      },
      {} as Record<string, any>,
    );
  }

  private _percentile(values: number[], p: number): number {
    const sorted = [...values].sort((a, b) => a - b);
    const index = Math.ceil((p / 100) * sorted.length) - 1;
    return sorted[Math.max(0, index)];
  }
}
```

### New API Endpoint: `src/app/api/benchmark/metrics/route.ts`

```typescript
// src/app/api/benchmark/metrics/route.ts

import { NextRequest, NextResponse } from "next/server";
import { BenchmarkCollector } from "@/lib/benchmark-collector";

const collector = new BenchmarkCollector();

export async function GET(request: NextRequest) {
  const summary = collector.getSummary();

  return NextResponse.json({
    timestamp: Date.now(),
    summary,
    // Target metrics
    targets: {
      tool_invocation_success_rate: { target: 0.99 },
      agent_handoff_latency_p95_ms: { target: 100 },
      context_propagation_latency_p95_ms: { target: 50 },
    },
  });
}
```

---

## Implementation Timeline

### Week 1: MCP 1.0 & Extended Tool Use

- [ ] Migrate `src/lib/mcp-client.ts` to MCP 1.0
- [ ] Update `src/middleware.ts` for new routing
- [ ] Update `src/lib/claude-client.ts` for extended tools
- [ ] Comprehensive testing of MCP changes

### Week 2: Handoff Protocols

- [ ] Implement `src/lib/agent-handoff.ts`
- [ ] Create `/api/agents/handoff` endpoint
- [ ] Register validation rules for agent pairs
- [ ] Integration testing with all agents

### Week 3-4: Memory Layer & Benchmarks

- [ ] Implement `src/lib/memory-layer.ts`
- [ ] Create Supabase migrations
- [ ] Implement `src/lib/benchmark-collector.ts`
- [ ] Create `/api/benchmark/metrics` endpoint
- [ ] End-to-end testing

---

## Deployment Considerations

### Backward Compatibility

- Maintain compatibility layer for deprecated MCP methods (temporary)
- Use feature flags for new handoff protocol
- Gradual rollout of extended tool use

### Monitoring & Alerting

- Track MCP routing errors
- Monitor handoff success rate (target: 99%+)
- Alert on context propagation latency spikes
- Benchmark regression detection

### Rollback Plan

- Keep MCP pre-1.0 server as fallback
- Store handoff decisions in audit log
- Version all context data for recovery

---

## Testing Checklist

- [ ] Unit tests for MCP 1.0 client
- [ ] Unit tests for handoff protocol
- [ ] Unit tests for memory layer
- [ ] Integration tests for API endpoints
- [ ] End-to-end agent handoff tests
- [ ] Context integrity verification
- [ ] Benchmark accuracy validation
- [ ] Load testing (100+ concurrent handoffs)
- [ ] Chaos testing (simulate MCP failures)

---

**Document Generated**: March 4, 2026 | **Status**: Ready for Development | **Next Review**: March 10, 2026
