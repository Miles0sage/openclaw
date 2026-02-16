# Router Examples & Use Cases

Real-world examples of how the intelligent router classifies queries and routes them to optimal models.

## Customer Support Use Case

### Example 1: Help Desk Inquiry

**Query:**

```
Hi, I can't log in to my account. It says my password is wrong but I'm sure I typed it correctly.
```

**Router Decision:**

- Complexity: 18/100
- Model: **Haiku** (75% cheaper)
- Confidence: 0.92
- Cost: $0.0000008

**Why Haiku:**

- Short greeting ("Hi")
- Simple problem statement
- No code or technical details
- One straightforward question

**Response Time:** ~500ms (Haiku is fast)
**Cost Savings:** $0.0000099 vs Sonnet

---

### Example 2: Technical Support

**Query:**

```
I'm getting a 502 Bad Gateway error when I try to upload files. Here's my error log:

2026-02-16 10:30:45 ERROR: Connection timeout in upload_handler.py line 234
2026-02-16 10:30:46 ERROR: Pool exhausted, max_connections=100
2026-02-16 10:30:47 ERROR: Retry failed after 3 attempts

What should I check?
```

**Router Decision:**

- Complexity: 52/100
- Model: **Sonnet** (baseline)
- Confidence: 0.78
- Cost: $0.000012

**Why Sonnet:**

- Multiple lines of code/logs
- Specific error investigation needed
- Debugging task (medium complexity)
- Needs troubleshooting analysis

---

### Example 3: Architecture Review

**Query:**

```
We're getting performance issues with our API. We currently have:
- Single PostgreSQL database (master-slave replication)
- Node.js Express servers behind a load balancer
- Redis cache for session management

We expect 100K requests/min in 6 months. What architectural changes should we make? Consider scaling, failover, and cost implications.
```

**Router Decision:**

- Complexity: 78/100
- Model: **Opus** (powerful reasoning)
- Confidence: 0.85
- Cost: $0.000045

**Why Opus:**

- Long query with architectural context
- Keywords: "architecture," "scaling," "cost," "implications"
- Strategic planning needed
- Multiple tradeoffs to evaluate
- Extended analysis required

---

## Development Use Case

### Example 1: Quick Question

**Query:**

```
How do I use async/await?
```

**Router Decision:**

- Complexity: 22/100
- Model: **Haiku**
- Confidence: 0.88
- Cost: $0.0000006

**Why Haiku:**

- Basic question
- Single concept
- No context needed

---

### Example 2: Bug Investigation

**Query:**

````
I'm getting a React hook error:
"Error: Invalid hook call"

Here's my component:

```typescript
function UserProfile({ userId }) {
  const [profile, setProfile] = useState(null);

  if (!userId) {
    return <div>Loading...</div>;
  }

  const { data } = useQuery(['profile', userId], () =>
    fetchProfile(userId)
  );

  return <div>{data?.name}</div>;
}
````

Why is this happening and how do I fix it?

```

**Router Decision:**
- Complexity: 48/100
- Model: **Sonnet**
- Confidence: 0.82
- Cost: $0.000011

**Why Sonnet:**
- Code debugging task
- Keywords: "error," "fix"
- Needs understanding of React rules
- Medium complexity investigation

---

### Example 3: Algorithm Optimization

**Query:**
```

I need to optimize a pathfinding algorithm for a game with a 1000x1000 grid. Currently using Dijkstra which takes 2-3 seconds per request. Requirements:

1. Must find path in < 100ms
2. Handle dynamic obstacles
3. Support multiple concurrent requests
4. Minimize memory usage

What algorithms should I consider? What are the tradeoffs between A\*, RRT, and hierarchical pathfinding? How would I implement caching?

```

**Router Decision:**
- Complexity: 82/100
- Model: **Opus**
- Confidence: 0.88
- Cost: $0.000052

**Why Opus:**
- Complex algorithmic problem
- Keywords: "optimize," "tradeoffs," "algorithm"
- Multiple considerations (speed, memory, concurrency)
- Strategic decision needed
- Advanced reasoning required

---

## Data Science Use Case

### Example 1: Quick Stats Question

**Query:**
```

What's the difference between mean and median?

```

**Router Decision:**
- Complexity: 15/100
- Model: **Haiku**
- Confidence: 0.95
- Cost: $0.0000005

**Why Haiku:**
- Definitional question
- No context needed
- Single concept

---

### Example 2: Analysis Help

**Query:**
```

I have a dataset with 10K customer records. I need to:

- Identify churn risk factors
- Build a simple predictive model
- Explain which features matter most

Here's a sample row:
customer_id, age, tenure_months, monthly_spend, support_tickets

What approach should I use? Should I use logistic regression or tree-based model?

```

**Router Decision:**
- Complexity: 55/100
- Model: **Sonnet**
- Confidence: 0.80
- Cost: $0.000013

**Why Sonnet:**
- Data analysis task
- Keywords: "model," "features," "approach"
- Methodological guidance needed
- Medium-complexity decision

---

### Example 3: Complex ML Architecture

**Query:**
```

Design a machine learning system for real-time fraud detection with these constraints:

1. Must process 50K transactions/second
2. Model latency < 50ms (p99)
3. Model size < 100MB
4. False positive rate < 0.5%
5. Must handle concept drift (fraud patterns evolve)

Should we use:

- Online learning with mini-batches?
- Ensemble of multiple models?
- Streaming architecture vs batch?

Consider hardware costs, operational complexity, and maintenance burden.

```

**Router Decision:**
- Complexity: 85/100
- Model: **Opus**
- Confidence: 0.87
- Cost: $0.000055

**Why Opus:**
- Complex ML system design
- Keywords: "design," "architecture," "tradeoffs," "constraints"
- Multiple considerations (speed, accuracy, cost, maintenance)
- Strategic planning required
- Advanced expertise needed

---

## Content Creation Use Case

### Example 1: Simple Content

**Query:**
```

Write a tweet about our new product launch

```

**Router Decision:**
- Complexity: 12/100
- Model: **Haiku**
- Confidence: 0.93
- Cost: $0.0000004

**Why Haiku:**
- Simple creative task
- No complex reasoning
- Quick output needed
- Standard template format

---

### Example 2: Marketing Copy

**Query:**
```

Write a compelling product description for our new API that emphasizes:

- 99.9% uptime SLA
- Sub-10ms response time
- Developer-friendly documentation

Target audience: Enterprise CTO/tech leads
Tone: Professional but approachable
Length: 100-150 words

```

**Router Decision:**
- Complexity: 38/100
- Model: **Sonnet**
- Confidence: 0.76
- Cost: $0.000010

**Why Sonnet:**
- Structured creative task
- Specific requirements and constraints
- Needs understanding of audience
- Medium complexity

---

### Example 3: Strategic Campaign

**Query:**
```

Our SaaS company is in competitive market. Design a content marketing strategy that:

1. Differentiates us from 3 main competitors
2. Targets decision-makers (CTOs, engineering leads)
3. Balances educational content with sales messaging
4. Can be executed by 2-person marketing team
5. Should drive qualified leads within 6 months

What channels, content pillars, and messaging should we use? What metrics matter most? How do we allocate budget?

```

**Router Decision:**
- Complexity: 76/100
- Model: **Opus**
- Confidence: 0.84
- Cost: $0.000048

**Why Opus:**
- Strategic planning task
- Keywords: "design," "strategy," "competitive," "differentiate"
- Multiple considerations (channels, budget, timeline)
- Advanced business reasoning
- Complex decision-making

---

## Cost Analysis Examples

### Scenario: 1,000 Queries/Day

```

Simple queries (40%): 400 queries
├─ Classified as Haiku
├─ Avg complexity: 18
├─ Avg tokens: 200
└─ Cost: 400 × $0.0000008 = $0.00032

Moderate queries (45%): 450 queries
├─ Classified as Sonnet
├─ Avg complexity: 50
├─ Avg tokens: 350
└─ Cost: 450 × $0.000012 = $0.0054

Complex queries (15%): 150 queries
├─ Classified as Opus
├─ Avg complexity: 80
├─ Avg tokens: 500
└─ Cost: 150 × $0.000045 = $0.00675

TOTAL WITH ROUTING: $0.01247/day = $0.374/month
TOTAL WITHOUT ROUTING (all Sonnet): $0.018/day = $0.54/month
SAVINGS: 30.6%

```

With better alignment to 70/20/10 distribution: **60-70% savings possible**.

---

## Real-Time Routing Example

### Request Flow

```

1. User sends message: "Help me debug this error"
   │
   ├─ Router receives request
   ├─ Classifies complexity: 42/100
   ├─ Selects model: Sonnet
   ├─ Estimates cost: $0.000011
   ├─ Confidence: 0.79
   │
   ├─ Dispatch uses: claude-3-5-sonnet-20241022
   ├─ Response: [bug debugging analysis]
   ├─ Actual tokens: input=120, output=280
   ├─ Actual cost: $0.000008
   │
   └─ Log event: { model: sonnet, cost: $0.000008, ...}

2. Next user: "Design microservices architecture"
   │
   ├─ Router receives request
   ├─ Classifies complexity: 78/100
   ├─ Selects model: Opus
   ├─ Estimates cost: $0.000042
   ├─ Confidence: 0.83
   │
   ├─ Dispatch uses: claude-opus-4-6
   ├─ Response: [comprehensive architecture guidance]
   ├─ Actual tokens: input=180, output=520
   ├─ Actual cost: $0.000039
   │
   └─ Log event: { model: opus, cost: $0.000039, ...}

3. Cost Summary (after 1000 queries):
   ├─ Total cost: $0.413
   ├─ Without routing: $1.32
   ├─ Savings: $0.907 (68.7%)
   └─ Distribution: Haiku 72%, Sonnet 18%, Opus 10%

```

---

## Model Selection Guide

### When to Route to Haiku

✓ Greetings and simple responses
✓ Formatting and text manipulation
✓ Quick factual questions
✓ Simple instructions
✓ Basic conversions
✓ First-pass analysis

**NOT ideal for:**
- Code debugging
- Creative work requiring nuance
- Analysis with multiple factors
- Strategic decisions

### When to Route to Sonnet

✓ Code review and debugging
✓ Feature implementation guidance
✓ Testing and quality assurance
✓ Documentation creation
✓ Moderate analysis tasks
✓ Most real-world development work

**Perfect for:**
- Balanced speed/quality/cost
- Most production workloads
- Teams with varied needs

### When to Route to Opus

✓ System architecture design
✓ Security analysis and threat modeling
✓ Algorithm optimization
✓ Strategic planning
✓ Complex business decisions
✓ Multi-factor analysis

**Worth the cost for:**
- High-stakes decisions
- Complex problem-solving
- Expert-level guidance
- Comprehensive analysis

---

## Monitoring Examples

### Daily Report

```

Date: 2026-02-16
Total Queries: 12,847

Distribution:

- Haiku: 8,993 (70.0%) | Cost: $0.087
- Sonnet: 2,569 (20.0%) | Cost: $0.154
- Opus: 1,285 (10.0%) | Cost: $0.173

Total Cost: $0.414
Without Routing: $1.320
Savings: $0.906 (68.6%)

Average Complexity: 42.3
Average Confidence: 0.81

Quality Metrics:

- User satisfaction: 4.7/5.0
- Error rate: 0.2%
- Avg response time: 1.2s

```

### Weekly Trend

```

Week Queries Cost Savings Complexity Confidence

---

Feb 9 89,129 $2.891 68.2% 41.2 0.80
Feb 10 92,456 $3.101 67.9% 42.1 0.81
Feb 11 87,654 $2.832 69.1% 40.8 0.82
Feb 12 94,287 $3.124 68.5% 42.3 0.80
Feb 13 91,203 $3.042 68.8% 41.9 0.81
Feb 14 88,456 $2.891 69.2% 41.1 0.83
Feb 15 90,123 $2.945 68.9% 41.8 0.81

---

TOTAL 633,308 $20.826 68.7% 41.7 0.81

```

---

## Troubleshooting Examples

### Issue: Too Many Queries Going to Opus

**Symptom:**
```

Distribution: Haiku 40%, Sonnet 30%, Opus 30%
Savings: 25% (should be 60-70%)

````

**Solution:**

Check what's being classified as complex:

```bash
curl -X POST http://localhost:18789/api/route/test \
  -d '{
    "queries": [
      "Query that routed to Opus",
      "Another Opus query"
    ]
  }'
````

Review the complexity scores. If too high:

- Adjust keyword weights
- Increase SONNET_THRESHOLD
- Review query patterns

### Issue: Haiku Performance Degradation

**Symptom:**

```
User complaint: "Responses are too short/incorrect for [task]"
Likely cause: Task is misclassified as Haiku
```

**Solution:**

1. Get the misclassified query
2. Test routing:

   ```bash
   curl -X POST http://localhost:18789/api/route \
     -d '{"query":"The problematic query"}'
   ```

3. If complexity is too low, add keywords to HIGH_COMPLEXITY_KEYWORDS
4. Or adjust task to be more explicit

---

## Summary

The router optimizes for:

- **Cost**: 60-70% savings vs baseline
- **Speed**: Haiku responses in <500ms
- **Quality**: Route complex work to powerful models
- **Simplicity**: Automatic classification, no manual tuning needed

Monitor the distribution and adjust keywords if needed. Most setups achieve 60-70% savings within 1-2 weeks of deployment.
