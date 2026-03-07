# MCP Server Directory Consolidation Analysis

**Date**: 2026-03-07
**Status**: PARTIAL CONSOLIDATION (split remains necessary)

---

## Summary

Wired `deep-research-mcp` into `/root/openclaw/.mcp.json`. The two MCP server directories (`mcp_servers/` and `mcp-servers/`) serve fundamentally different purposes and **cannot be consolidated without breaking imports**.

### What Was Wired
- **deep-research-mcp**: Added to `.mcp.json` as a Node.js stdio server
  - Command: `node /root/openclaw/mcp-servers/deep-research-mcp/dist/index.js`
  - Requires: `PERPLEXITY_API_KEY` environment variable (already in `.env`)
  - Tools: `deep_research` (autonomous research with sub-question decomposition)
  - Config location: `/root/openclaw/.mcp.json` (lines 25-31)

---

## Directory Structure

### `/root/openclaw/mcp_servers/` (Python, with underscore)
**Purpose**: Vertical MCP tool servers for business domains (restaurants, barbershops)

```
mcp_servers/
  ├── __init__.py                 # Package header
  ├── pyproject.toml              # Python package config (fastmcp)
  ├── shared/                     # Shared utilities
  │   └── billing.py              # APIKeyManager, UsageTracker, billing_check
  ├── restaurant/                 # Restaurant operations MCP server
  │   ├── server.py               # MCP server definition (7 tools)
  │   └── server.json             # Config (stdio + HTTP modes)
  └── barbershop/                 # Barbershop/salon operations MCP server
      ├── server.py               # MCP server definition (7 tools)
      └── server.json             # Config (stdio + HTTP modes)
```

**Technology Stack**: FastMCP, Python 3.11+, can run in stdio or HTTP mode
**Import Pattern**: `from mcp_servers.<vertical>.server import mcp`
**Active Users**: `/root/openclaw/routers/workflows.py` (lines 581-654)

### `/root/openclaw/mcp-servers/` (TypeScript, with hyphen)
**Purpose**: General-purpose MCP servers (research, browser, memory, web crawling)

```
mcp-servers/
  └── deep-research-mcp/          # Multi-step autonomous research
      ├── package.json            # npm/TypeScript config
      ├── src/
      │   ├── index.ts            # MCP server + tool definitions
      │   ├── research-engine.ts   # Question decomposition, synthesis
      │   └── perplexity.ts        # Perplexity Sonar API client
      ├── dist/                    # Compiled JavaScript (production)
      └── node_modules/            # Dependencies
```

**Technology Stack**: TypeScript, Node.js (ESM), compiled to JavaScript
**Package Standard**: Published as npm package (bin: `deep-research-mcp`)
**Future Servers**: chrome-devtools, playwright, etc. go here

---

## Why Consolidation is NOT Feasible

### Import Breakage
The Python vertical servers are **dynamically imported** at runtime in `/root/openclaw/routers/workflows.py`:

```python
# Line 590-592
if server_name == "restaurant":
    from mcp_servers.restaurant.server import mcp as srv
elif server_name == "barbershop":
    from mcp_servers.barbershop.server import mcp as srv
```

Renaming `mcp_servers/` to `mcp-servers/python/` would require:
1. Update all imports in `routers/workflows.py` (6 locations)
2. Update billing module path references (3 locations)
3. Risk breaking deployed instances using old paths
4. Invalidate documentation and deployment scripts

### Purpose Divergence
- **Python MCP servers** (`mcp_servers/`): Mission-critical business tools with rate limiting, API key management, billing integration
- **TypeScript MCP servers** (`mcp-servers/`): Research/utility servers without billing constraints

Merging them would complicate:
- Deployment (mixed Python/Node.js builds)
- Dependencies (Python fastmcp vs Node.js SDK)
- Permission models (vertical servers need billing gates)

---

## Current .mcp.json Configuration

**Location**: `/root/openclaw/.mcp.json`

```json
{
  "mcpServers": {
    "tree-sitter": {
      "command": "mcp-server-tree-sitter",
      "args": []
    },
    "chrome-devtools": {
      "command": "chrome-devtools-mcp",
      "args": ["--autoConnect"]
    },
    "mem0": {
      "command": "npx",
      "args": ["-y", "@mem0/mcp-server"],
      "env": {
        "MEM0_API_KEY": "m0-BN1oF7rH720Y2JmmSbGxj9cncZy4cdnS8m3UPoKyh"
      }
    },
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "fc-aac4b5382aff41a080c103a2f1477701"
      }
    },
    "deep-research-mcp": {
      "command": "node",
      "args": ["/root/openclaw/mcp-servers/deep-research-mcp/dist/index.js"],
      "env": {
        "PERPLEXITY_API_KEY": "${PERPLEXITY_API_KEY}"
      }
    }
  }
}
```

**Notes on deep-research-mcp entry**:
- Uses absolute path (not npm package) for reproducibility
- `${PERPLEXITY_API_KEY}` syntax expects environment variable substitution at runtime
- Falls back to `.env` file if MCP client supports it (Cursor, Claude Code, Anthropic SDK)

---

## What's NOT in .mcp.json

### Python Vertical Servers (restaurant, barbershop)
These are **NOT** in `.mcp.json` because:

1. **Routed via FastAPI**: Called through HTTP endpoints (`/api/mcp/{server_name}/tools`, `/api/mcp/call`)
2. **Require billing gates**: APIKeyManager/UsageTracker check every call before reaching the tool
3. **Multi-mode capable**: Can run stdio OR HTTP depending on deployment

The FastAPI routing pattern is:
```
Client → /api/mcp/call → workflows.py → dynamic import → billing check → srv.call_tool()
```

This design allows:
- Rate limiting per API key and server
- Usage tracking and billing
- Central gateway authentication
- No need for separate MCP server processes

---

## Recommendations

### Short Term (Ship Now)
✅ deep-research-mcp is wired and ready
✅ No breaking changes to existing imports
✅ MCP directory split is intentional and correct

### Medium Term (v4.2+)
1. **Document the split** in `/root/openclaw/MCP_SERVERS_GUIDE.md`
2. **Add more TypeScript MCP servers** to `mcp-servers/`:
   - Browser automation (Playwright)
   - Code execution (safer sandbox)
   - Custom research tools
3. **Keep Python vertical servers separate** in `mcp_servers/` with their billing layer

### Long Term
- Monitor if FastAPI HTTP routing becomes a bottleneck
- Only consider consolidation if a unifying abstraction emerges (e.g., unified billing layer for both)
- Otherwise, let them evolve in parallel: Python for business tools, TypeScript for research/utility

---

## Verification Checklist

- [x] deep-research-mcp builds without errors (`npm run build`)
- [x] dist/index.js is executable and has proper shebang
- [x] PERPLEXITY_API_KEY is in `.env` and accessible
- [x] .mcp.json syntax is valid JSON
- [x] No imports in main codebase are broken
- [x] Commit created and pushed

---

## Files Changed
- `/root/openclaw/.mcp.json` — Added deep-research-mcp entry
- This document — `/root/openclaw/MCP_CONSOLIDATION.md`

---

**Commit**: `709591327` — "Wire deep-research-mcp into .mcp.json configuration"
