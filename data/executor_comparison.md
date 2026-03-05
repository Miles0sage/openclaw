# Executor Comparison Report

## Overview
This report compares the **Grok Executor** and **MiniMax Executor** used in the OpenClaw codebase as fallback code generation backends.

---

## Tool Calling Support

| Executor | Tool Calling Support |
|----------|---------------------|
| **Grok** | ❌ No |
| **MiniMax** | ❌ No |

Both executors return an empty `"tool_calls": []` array in their response dictionaries, indicating **neither supports tool calling**. They use standard OpenAI-compatible chat completion APIs without the `tools` parameter.

---

## Cost Comparison

### Grok Executor Pricing (per 1M tokens)

| Model | Input Cost | Output Cost |
|-------|-----------|-------------|
| `grok-3` | $3.00 | $15.00 |
| `grok-3-mini` | $0.30 | $0.50 |
| `grok-code-fast-1` | $0.30 | $0.50 |

### MiniMax Executor Pricing (per 1M tokens)

| Model | Input Cost | Output Cost |
|-------|-----------|-------------|
| `MiniMax-M2.5` | $0.30 | $1.20 |

---

## Cost Analysis

### Cheapest Option: **MiniMax** (for most tasks)

- **MiniMax-M2.5**: $0.30 input / $1.20 output
- **Grok-3-mini**: $0.30 input / $0.50 output (cheaper output!)

However, Grok-3-mini has a significant output cost advantage at $0.50 vs $1.20 for MiniMax.

### For High-Volume Text Generation:
- **grok-3-mini** is cheapest at $0.30/$0.50 — ideal for simple, high-volume tasks

### For Complex Tasks (P0 Priority):
- **Grok-3** is used for P0 tasks at $3/$15 (expensive!)
- MiniMax is consistently $0.30/$1.20

---

## Summary

| Criteria | Winner |
|----------|--------|
| **Tool Calling** | Neither (both ❌) |
| **Cheapest Input** | Tie ($0.30) |
| **Cheapest Output** | **Grok-3-mini** ($0.50 vs $1.20) |
| **Best for P0 Tasks** | Both use their premium models |
| **Best Overall Value** | **MiniMax** (consistently $0.30/$1.20) |

---

## Recommendation

- Use **MiniMax** for most fallback tasks due to consistent pricing
- Use **grok-3-mini** if output-heavy tasks dominate (50% cheaper output)
- Neither should be used if tool calling is required — consider OpenCode/Gemini as the primary
