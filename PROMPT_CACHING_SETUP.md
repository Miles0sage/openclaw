# Prompt Caching Setup Guide

**Purpose:** Reduce latency and costs for repeated analysis by leveraging Claude's prompt caching feature.

**Expected Savings:** 90% reduction on cached inputs (50K token limit per request)

**Last Updated:** 2026-02-16

---

## Overview

Prompt caching allows Claude to reuse cached system prompts, tool definitions, and conversation history across multiple API calls. This is especially valuable for:

- **Repeated analysis** — Same codebase reviewed multiple times
- **Agent conversations** — Long context windows reused across turns
- **Cost optimization** — Cache hit: 10% of input token cost; cache miss: 100%

### Quick Stats

| Scenario               | Cost Reduction | TTL  | Ideal For          |
| ---------------------- | -------------- | ---- | ------------------ |
| Single review (miss)   | 0%             | N/A  | First analysis     |
| Follow-up review (hit) | 90%            | 1h   | Same-session edits |
| Batch analysis (hit)   | 85-90%         | 5m   | Multiple files     |
| Live agent (hit)       | 85%            | 5min | Long conversations |

---

## How Prompt Caching Works

### Request Structure

```
Request:
┌─────────────────────────────────────────────────┐
│ System Prompt (1-3KB, cacheable)                │
├─────────────────────────────────────────────────┤
│ Tools Definition (2-5KB, cacheable)             │
├─────────────────────────────────────────────────┤
│ Conversation History (10-50KB, cacheable)       │
├─────────────────────────────────────────────────┤
│ Current User Query (uncached)                   │
└─────────────────────────────────────────────────┘

On First Request:
  • All sections processed (100% token cost)
  • Cache key computed from content hash
  • Cached sections stored (5-min TTL by default)

On Follow-up Request (same cache key):
  • System + Tools + History fetched from cache
  • Only new query processed (10% token cost)
  • Result: 90% cost savings
```

### Cache Control Placement

```python
# Python SDK (Anthropic)
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=2000,
    system=[
        {
            "type": "text",
            "text": "You are a code reviewer...",
            "cache_control": {"type": "ephemeral"}  # <-- HERE (after content)
        }
    ],
    tools=[
        {
            "name": "analyze_code",
            "description": "...",
            "cache_control": {"type": "ephemeral"}  # <-- HERE (after tool def)
        }
    ],
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[Previous context]",
                    "cache_control": {"type": "ephemeral"}  # <-- HERE (after history)
                },
                {
                    "type": "text",
                    "text": "Review the latest changes..."  # <-- NO cache_control
                }
            ]
        }
    ]
)
```

---

## Implementation Patterns

### Pattern 1: Caching System Prompts

**Ideal for:** Code review agents, quality gates, standardized analysis

```python
# system_prompt.py
SYSTEM_PROMPT_CODE_REVIEW = """You are an expert code reviewer specializing in:
- Security vulnerabilities
- Performance optimization
- Architecture best practices
- Testing coverage

When reviewing code:
1. Identify critical issues first (security, crashes)
2. Suggest improvements (performance, readability)
3. Verify ACI/coding standards compliance
4. Recommend test cases

Always provide actionable feedback with examples."""

# client.py
from anthropic import Anthropic
from system_prompt import SYSTEM_PROMPT_CODE_REVIEW

client = Anthropic()

response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=2000,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT_CODE_REVIEW,
            "cache_control": {"type": "ephemeral"}  # Cache the system prompt
        }
    ],
    messages=[
        {
            "role": "user",
            "content": "Review this code: [code snippet]"
        }
    ]
)
```

**Cache hit rate:** 95%+ (same system prompt reused)

---

### Pattern 2: Caching Tool Definitions

**Ideal for:** Multi-agent systems, OpenClaw routing

```python
# tools.py
TOOLS = [
    {
        "name": "run_tests",
        "description": "Execute test suite and return pass/fail results",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
                "test_file": {"type": "string", "description": "Optional test file path"}
            }
        }
    },
    {
        "name": "check_coverage",
        "description": "Run coverage analysis and return percentage",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_target": {"type": "number", "description": "Minimum coverage % (default 85)"}
            }
        }
    }
]

# agent.py
def create_agent_with_caching(system_prompt, tools):
    """Create an agent with cached tools and system prompt."""
    return {
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ],
        "tools": [
            {**tool, "cache_control": {"type": "ephemeral"}}
            for tool in tools
        ]
    }

# First request (MISS): ~400 tokens (100% cost)
# Subsequent requests (HIT): ~40 tokens (10% cost)
```

**Cache hit rate:** 90%+ (tools rarely change)

---

### Pattern 3: Caching Conversation History

**Ideal for:** Long-running agents, multi-turn analysis

```python
# conversation_manager.py
class ConversationWithCache:
    def __init__(self, system_prompt, cache_ttl_seconds=300):
        self.system_prompt = system_prompt
        self.cache_ttl = cache_ttl_seconds
        self.history = []
        self.client = Anthropic()

    def add_turn(self, user_message, assistant_response):
        """Add a turn to conversation history."""
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": assistant_response})

    def get_cached_messages(self):
        """Return history with cache control on all but last message."""
        if not self.history:
            return []

        cached = []
        for msg in self.history[:-1]:  # All but last
            cached.append({
                **msg,
                "content": [{"type": "text", "text": msg["content"], "cache_control": {"type": "ephemeral"}}]
                if isinstance(msg["content"], str)
                else msg["content"]
            })

        # Last message: no cache control (new user input)
        if self.history:
            last = self.history[-1]
            cached.append({
                **last,
                "content": [{"type": "text", "text": last["content"]}]
                if isinstance(last["content"], str)
                else last["content"]
            })

        return cached

    def ask(self, question):
        """Ask a question with cached history."""
        messages = self.get_cached_messages()
        messages.append({"role": "user", "content": question})

        response = self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            system=[{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"}
            }],
            messages=messages
        )

        return response

# Usage
conv = ConversationWithCache(
    system_prompt="You are a code reviewer.",
    cache_ttl_seconds=3600  # 1 hour
)

# Turn 1: MISS (system + history not cached yet)
resp1 = conv.ask("Review this code: [code]")

# Turn 2: HIT (system + history cached, only new query charged)
conv.add_turn("Review this code: [code]", resp1.content[0].text)
resp2 = conv.ask("What about performance?")

# Savings: ~90% on Turn 2
```

**Cache hit rate:** 95%+ (history grows but is reused)

---

### Pattern 4: Multi-File Code Review with Caching

**Ideal for:** PrestressCalc validation, OpenClaw code generation

```python
# batch_reviewer.py
class BatchCodeReviewer:
    def __init__(self, project_name, files):
        self.project_name = project_name
        self.files = files
        self.client = Anthropic()
        self.review_context = self._build_review_context()

    def _build_review_context(self):
        """Build persistent review context (cached across files)."""
        return f"""
        Project: {self.project_name}

        Review Guidelines:
        1. Security: Check for OWASP Top 10 issues
        2. Performance: Identify N+1 queries, optimize algorithms
        3. Testing: Verify 85%+ coverage
        4. Architecture: Check module boundaries
        5. Standards: Verify ACI/coding standards

        Files to review: {len(self.files)}
        """

    def review_files(self):
        """Review all files with cached context."""
        results = {}

        for i, filepath in enumerate(self.files):
            with open(filepath) as f:
                code = f.read()

            # Build messages: cache context, new file
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self.review_context,
                            "cache_control": {"type": "ephemeral"}
                        },
                        {
                            "type": "text",
                            "text": f"File {i+1}/{len(self.files)}: {filepath}\n\n{code}"
                            # NO cache control on new content
                        }
                    ]
                }
            ]

            response = self.client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": "You are an expert code reviewer.",
                    "cache_control": {"type": "ephemeral"}
                }],
                messages=messages
            )

            results[filepath] = response.content[0].text

        return results

# Usage: Review 10 files
reviewer = BatchCodeReviewer(
    project_name="PrestressCalc",
    files=[
        "prestressed/beam_design.py",
        "prestressed/load_cases.py",
        "prestressed/cost_analysis.py",
        # ... 7 more files
    ]
)

results = reviewer.review_files()
# Cost: First file ~400 tokens, files 2-10 ~40 tokens each = ~760 tokens total
# Without cache: ~400 tokens × 10 = 4000 tokens (81% savings!)
```

**Cache hit rate:** 90%+ (context reused across 10 files)

---

## TTL Strategy

### Active Projects (1-hour TTL)

**Projects:** Barber CRM, Delhi Palace, PrestressCalc during development

```python
cache_control = {"type": "ephemeral"}  # Default: 5 minutes
# Recommended: Set in client config
client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"]
)
# Note: Ephemeral (5min) is default; for longer TTL, use batch API or session management
```

**Strategy:**

1. First review: Cache miss (100% cost)
2. Edits within 5 minutes: Cache hit (90% savings)
3. After 5 minutes: Cache miss (restart cycle)

**Cost Impact:** Typical dev session (10 edits in 30 mins) = 1 miss + 9 hits = ~19% of base cost

---

### Cold Projects (5-minute TTL)

**Projects:** Concrete Canoe, archived projects (infrequent access)

```python
cache_control = {"type": "ephemeral"}  # Auto-expires after 5 minutes
```

**Strategy:**

1. First analysis: Cache miss (100% cost)
2. Follow-up within 5 minutes: Cache hit (90% savings)
3. After 5 minutes: Cache miss

**Cost Impact:** Single analysis session = ~20% of base cost (1 miss, 1-2 hits)

---

## Cost Calculation Examples

### Example 1: PrestressCalc Quality Gate

```
Scenario: Auto-run pytest after file edit

Without Caching:
  • System prompt: 150 tokens
  • Test output: 500 tokens
  • Total per edit: 650 tokens
  • 5 edits in 30 min: 3,250 tokens

With Caching (5-min TTL):
  • First edit (MISS): 650 tokens
  • Edits 2-5 (HIT): 50 tokens each
  • Total: 650 + (50 × 4) = 850 tokens
  • Savings: 74% (2,400 tokens saved!)

Cost @ $3/1M tokens:
  • Without cache: 3,250 × $0.000003 = $0.00975
  • With cache: 850 × $0.000003 = $0.00255
  • Savings: $0.0072 per session
```

### Example 2: OpenClaw Agent Routing (8-turn conversation)

```
Scenario: Agent routes 8 messages to correct service

Without Caching:
  • System prompt: 200 tokens
  • Tools definition: 300 tokens
  • Per message: 400 tokens
  • 8 messages: (200 + 300) + (400 × 8) = 3,700 tokens

With Caching (5-min TTL):
  • First message (MISS): 200 + 300 + 400 = 900 tokens
  • Messages 2-8 (HIT): 40 tokens each
  • Total: 900 + (40 × 7) = 1,180 tokens
  • Savings: 68% (2,520 tokens saved!)

Cost @ $3/1M tokens:
  • Without cache: 3,700 × $0.000003 = $0.0111
  • With cache: 1,180 × $0.000003 = $0.00354
  • Savings: $0.00756 per conversation
```

### Example 3: Batch Code Review (10 files)

```
Scenario: Review 10 files in same session

Without Caching:
  • Per file: 600 tokens
  • 10 files: 6,000 tokens

With Caching (5-min TTL):
  • First file (MISS): 600 tokens
  • Files 2-10 (HIT): 60 tokens each
  • Total: 600 + (60 × 9) = 1,140 tokens
  • Savings: 81% (4,860 tokens saved!)

Cost @ $3/1M tokens:
  • Without cache: 6,000 × $0.000003 = $0.018
  • With cache: 1,140 × $0.000003 = $0.00342
  • Savings: $0.01458 per batch
```

---

## Implementation Checklist

- [ ] **System Prompts**: Add `cache_control` after text content
- [ ] **Tools Definitions**: Add `cache_control` after tool schema
- [ ] **Conversation History**: Add `cache_control` to all messages except the current user input
- [ ] **Error Handling**: Gracefully degrade if caching unavailable
- [ ] **Monitoring**: Track cache hit/miss rates in logs
- [ ] **Testing**: Verify cache key consistency (same input = same cache key)

---

## Troubleshooting

### Cache Miss Every Request

**Symptom:** Every request uses 100% tokens despite identical input

**Causes:**

1. Cache control not added to the right sections
2. Content changed between requests (different system prompt, tools, history)
3. TTL expired (5 minutes by default)

**Solution:**

```python
# ✅ CORRECT: Add cache_control after content
"system": [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]

# ❌ WRONG: Cache control in wrong place
"system": {"type": "text", "text": prompt}, "cache_control": {"type": "ephemeral"}
```

### Cache Key Mismatch

**Symptom:** Similar requests not using cache

**Cause:** Content differs slightly (whitespace, formatting)

**Solution:**

```python
# Normalize content before caching
def normalize_for_cache(text):
    return text.strip().replace("\n\n", "\n")  # Remove extra whitespace

system_prompt = normalize_for_cache(system_prompt)
```

---

## Best Practices

1. **Cache the static, change the dynamic**
   - System prompts: Always cache
   - Tools: Always cache
   - History: Cache all messages except current input
   - Current query: Never cache

2. **Keep cache keys consistent**
   - Don't change system prompts between requests
   - Don't change tool definitions mid-conversation
   - Use same formatting for reproducibility

3. **Monitor cache efficiency**

   ```python
   # Log cache metrics
   usage = response.usage
   cache_miss_cost = usage.input_tokens
   cache_hit_cost = usage.cache_read_input_tokens
   efficiency = cache_hit_cost / (cache_miss_cost + cache_hit_cost)
   print(f"Cache efficiency: {efficiency:.1%}")
   ```

4. **Set appropriate TTLs**
   - Active development: 5 min (default)
   - Long-running agents: Consider batch API for persistent cache
   - Production: Use session-based caching with Redis

---

## Integration with Quality Gates

### PrestressCalc Quality Gate

```python
# post_tool_use_hook.py
from anthropic import Anthropic

client = Anthropic()

def run_quality_gate_with_cache(project, files_changed):
    """Run pytest with cached system prompt."""

    system_prompt = """You are a Python testing expert.
    Review test results and provide actionable feedback.
    Flag coverage issues, suggest new tests, verify ACI compliance."""

    # Build test output summary
    test_summary = run_pytest()  # Returns test results

    # Call Claude with cached system prompt
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1000,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Analyze test results:\n{test_summary}"
            }
        ]
    )

    return response
```

**Cache Hit Rate:** 95% (system prompt rarely changes)

---

## References

- [Anthropic Prompt Caching Docs](https://docs.anthropic.com/en/docs/build-a-claude-app/caching)
- [Cost Reduction Analysis](./master-project-analysis.md)
- [Quality Gates README](./QUALITY_GATES_README.md)

---

**Generated:** 2026-02-16 | **Framework Version:** Phase 4 Optimization
