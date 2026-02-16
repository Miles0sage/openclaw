# 🧪 OpenClaw Model Evaluation Guide

**Test and compare AI model capabilities automatically!**

---

## 🎯 What This Does

The Model Evaluator tests AI models across 5 key capabilities:

1. **💻 Code Generation** - Can it write functional code?
2. **🧠 Logical Reasoning** - Can it solve logic puzzles?
3. **📋 Instruction Following** - Does it follow complex instructions?
4. **🔍 Context Understanding** - Can it understand relationships?
5. **⚡ Speed** - How fast does it respond?

**Output:** Comparison report showing which models are best for what!

---

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
pip3 install anthropic requests
```

### Step 2: Set API Keys

```bash
# For Anthropic models (Claude)
export ANTHROPIC_API_KEY="your-key-here"

# For Ollama (already running if you followed 24/7 setup)
# No API key needed!
```

### Step 3: Run Evaluation

```bash
cd /root/openclaw
python3 model-evaluator.py
```

**That's it!** The evaluator will:

1. Detect available models (Anthropic + Ollama)
2. Run 5 tests on each model
3. Generate comparison report
4. Save results to JSON

---

## 📊 Example Output

```
🧪 Starting Model Evaluation
============================================================
Testing 6 models
============================================================

📊 Testing: Claude Sonnet 4.5
------------------------------------------------------------
✅ Code Generation: 100/100 (1234ms)
✅ Logical Reasoning: 100/100 (987ms)
✅ Instruction Following: 95/100 (765ms)
✅ Context Understanding: 100/100 (543ms)
✅ Speed Test: 80/100 (1234ms)

📊 Testing: qwen2.5-coder:14b
------------------------------------------------------------
✅ Code Generation: 100/100 (3456ms)
✅ Logical Reasoning: 80/100 (2345ms)
✅ Instruction Following: 85/100 (2876ms)
✅ Context Understanding: 75/100 (2543ms)
✅ Speed Test: 40/100 (4567ms)

================================================================================
📊 MODEL EVALUATION REPORT
================================================================================

🏆 OVERALL SCORES
--------------------------------------------------------------------------------
Claude Sonnet 4.5              | Score:  95.0 | Latency:   950ms | Tokens: 1234
Claude Opus 4.6                | Score:  97.0 | Latency:  1200ms | Tokens: 1456
Claude Haiku 4.5               | Score:  85.0 | Latency:   600ms | Tokens: 987
qwen2.5-coder:14b              | Score:  88.0 | Latency:  3157ms | Tokens: 2345
qwen2.5:14b                    | Score:  82.0 | Latency:  2987ms | Tokens: 2123
deepseek-coder-v2:16b          | Score:  90.0 | Latency:  3456ms | Tokens: 2567

🎯 RECOMMENDATIONS
--------------------------------------------------------------------------------
Best Overall:     Claude Opus 4.6 (97.0/100)
Fastest:          Claude Haiku 4.5 (600ms)
Most Efficient:   Claude Haiku 4.5

================================================================================
```

---

## 🎯 Supported Models

### Anthropic (Cloud)

- ✅ Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)
- ✅ Claude Opus 4.6 (`claude-opus-4-6`)
- ✅ Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)

**Pros:** Highest quality, fast, reliable
**Cons:** Costs money ($)

### Ollama (Local)

- ✅ Qwen 2.5 Coder 14B (`qwen2.5-coder:14b`)
- ✅ Qwen 2.5 14B (`qwen2.5:14b`)
- ✅ DeepSeek Coder V2 16B (`deepseek-coder-v2:16b`)
- ✅ CodeLlama 13B (`codellama:13b`)
- ✅ Llama 3.3 70B (`llama3.3:70b`)
- ✅ Any other Ollama model installed

**Pros:** Free, private, no API limits
**Cons:** Slower, requires GPU

### Coming Soon

- 🔜 OpenAI (GPT-4, GPT-4 Turbo, GPT-3.5)
- 🔜 Google (Gemini Pro, Gemini Ultra)
- 🔜 OpenRouter (100+ models)
- 🔜 Local LLaMA.cpp models

---

## 🧪 Test Details

### Test 1: Code Generation

**Prompt:**

```
Write a Python function that:
1. Takes a list of numbers
2. Filters out negative numbers
3. Squares the remaining numbers
4. Returns the sum

Include type hints and a docstring.
```

**Scoring:**

- Has valid code: 50 points
- Has docstring: 25 points
- Has type hints: 25 points

**What it tests:** Can the model write functional, well-documented code?

---

### Test 2: Logical Reasoning

**Prompt:**

```
Solve this logic puzzle:

There are 3 boxes: red, blue, green.
- One contains gold, one contains silver, one is empty.
- All labels are incorrect.
- The red box is labeled "gold"
- The blue box is labeled "empty"
- The green box is labeled "silver"

Which box contains gold? Explain your reasoning.
```

**Scoring:**

- Correct answer: 50 points
- Shows reasoning: 30 points
- Step-by-step explanation: 20 points

**What it tests:** Can the model solve logic puzzles and explain reasoning?

---

### Test 3: Instruction Following

**Prompt:**

```
Follow these exact instructions:
1. Count backwards from 5 to 1
2. For each number, write "Number" followed by the digit
3. After each line, add an emoji (🔢)
4. End with "Done!"
5. Do NOT add any other text
```

**Scoring:**

- Has all numbers: 25 points
- Uses "Number" prefix: 25 points
- Includes emoji: 20 points
- Ends with "Done!": 15 points
- No extra text: 15 points

**What it tests:** Can the model follow precise instructions without adding extras?

---

### Test 4: Context Understanding

**Prompt:**

```
Context:
- Alice is a software engineer
- Bob is Alice's manager
- Carol reports to Bob
- David is Carol's teammate

Question: If Alice gets promoted to Bob's level,
who would Carol report to?
```

**Scoring:**

- Mentions Carol: 40 points
- Explains relationship: 40 points
- Concise answer: 20 points

**What it tests:** Can the model understand context and relationships?

---

### Test 5: Speed Test

**Prompt:**

```
Say 'Hello, World!' and nothing else.
```

**Scoring:**

- < 1 second: 100 points
- < 2 seconds: 80 points
- < 3 seconds: 60 points
- < 5 seconds: 40 points
- > 5 seconds: 20 points

**What it tests:** Raw response speed

---

## 🎮 Advanced Usage

### Evaluate Specific Models Only

Edit `model-evaluator.py`:

```python
# Only test Anthropic models
evaluator.add_anthropic_models(api_key)

# Don't add Ollama
# evaluator.add_ollama_models()  # Commented out
```

### Add Custom Tests

```python
async def test_creativity(self, model: ModelConfig) -> TestResult:
    """Test 6: Creative writing"""
    prompt = "Write a haiku about AI"

    start_time = time.time()
    response, tokens = await self._call_model(model, prompt)
    latency_ms = int((time.time() - start_time) * 1000)

    # Check if it's a haiku (3 lines)
    lines = response.strip().split("\n")
    is_haiku = len(lines) == 3

    return TestResult(
        model_id=model.id,
        test_name="Creative Writing",
        passed=is_haiku,
        score=100 if is_haiku else 50,
        response=response,
        latency_ms=latency_ms,
        tokens_used=tokens
    )

# Add to tests list
tests = [
    self.test_code_generation,
    self.test_reasoning,
    self.test_instruction_following,
    self.test_context_understanding,
    self.test_speed,
    self.test_creativity  # New!
]
```

### Compare Cost Efficiency

```python
# Add to generate_report()
report.append("\n💰 COST ANALYSIS")
report.append("-" * 80)

for model_id, data in model_scores.items():
    model = next(m for m in self.models if m.id == model_id)

    if model.provider == "anthropic":
        # Rough cost estimate (Claude pricing)
        cost_per_1k_tokens = 0.003  # Haiku pricing
        estimated_cost = (data["tokens"] / 1000) * cost_per_1k_tokens
        report.append(f"{data['name']:30} ${estimated_cost:.4f}")
    elif model.provider == "ollama":
        report.append(f"{data['name']:30} $0.0000 (FREE!)")
```

---

## 📈 Interpreting Results

### Overall Score

- **90-100:** Excellent - Use for production
- **75-89:** Good - Suitable for most tasks
- **60-74:** Acceptable - Specific use cases
- **<60:** Limited - May need fine-tuning

### Speed

- **<1s:** Excellent - Real-time chat
- **1-3s:** Good - User won't notice
- **3-5s:** Acceptable - Slight delay
- **>5s:** Slow - Consider faster model

### Recommendations

**For Coding Tasks:**

- Best: Claude Opus 4.6 or Qwen2.5-Coder
- Fastest: Claude Haiku 4.5
- Free: Qwen2.5-Coder (Ollama)

**For Chat/Reasoning:**

- Best: Claude Sonnet 4.5
- Fastest: Claude Haiku 4.5
- Free: Qwen2.5 (Ollama)

**For Production (24/7):**

- Best balance: Claude Sonnet 4.5 (primary) + Qwen2.5-Coder (fallback)
- All free: Qwen2.5-Coder + DeepSeek-Coder-V2

---

## 🔧 Integration with OpenClaw

### Use Evaluation Results in Config

After running evaluation, update `config.json`:

```json
{
  "agents": {
    "project_manager": {
      "model": "claude-sonnet-4-5-20250929",
      "reason": "Best overall score (95/100)"
    },
    "coder_agent": {
      "model": "qwen2.5-coder:14b",
      "reason": "Best code generation, free"
    },
    "hacker_agent": {
      "model": "qwen2.5:14b",
      "reason": "Good reasoning, free"
    }
  },
  "fallbacks": {
    "enabled": true,
    "chain": [
      "claude-sonnet-4-5-20250929",
      "ollama/qwen2.5-coder:14b",
      "claude-haiku-4-5-20251001"
    ],
    "reason": "Claude primary, Ollama fallback for cost savings"
  }
}
```

### Automatic Model Selection

Create `auto-select-models.py`:

```python
import json

# Load evaluation results
with open("model_evaluation_results.json") as f:
    results = json.load(f)

# Calculate scores
model_scores = {}
for result in results["results"]:
    model_id = result["model_id"]
    if model_id not in model_scores:
        model_scores[model_id] = []
    model_scores[model_id].append(result["score"])

# Get averages
averages = {
    model_id: sum(scores) / len(scores)
    for model_id, scores in model_scores.items()
}

# Sort by score
sorted_models = sorted(averages.items(), key=lambda x: x[1], reverse=True)

print("🏆 Recommended Model Assignment:")
print(f"PM:       {sorted_models[0][0]} ({sorted_models[0][1]:.1f}/100)")
print(f"Coder:    {sorted_models[1][0]} ({sorted_models[1][1]:.1f}/100)")
print(f"Security: {sorted_models[2][0]} ({sorted_models[2][1]:.1f}/100)")
```

---

## 🎯 Real-World Example

### Scenario: Optimize for Cost

**Goal:** Find the cheapest model that still performs well

**Step 1:** Run evaluation

```bash
python3 model-evaluator.py
```

**Step 2:** Analyze results

```
Claude Opus 4.6:      97/100, 1200ms, $$$$ (expensive!)
Claude Sonnet 4.5:    95/100,  950ms, $$   (moderate)
Qwen2.5-Coder:        88/100, 3157ms, FREE (local)
```

**Step 3:** Decision

For 24/7 autonomous coding:

- **Primary:** Qwen2.5-Coder (free, good scores)
- **Fallback:** Claude Haiku 4.5 (fast, cheap)
- **Critical tasks:** Claude Sonnet 4.5 (best quality)

**Savings:** ~$500/month vs all-Claude setup!

---

## 🔄 Continuous Evaluation

### Run Weekly Benchmarks

```bash
# Create cron job
crontab -e

# Add this line (runs every Monday at 3 AM)
0 3 * * 1 cd /root/openclaw && python3 model-evaluator.py > evaluation_$(date +\%Y\%m\%d).log
```

**Why?** Models improve over time. Re-evaluate to catch:

- New Ollama models
- Updated Claude models
- Performance improvements

---

## 📊 Sample Report

```
================================================================================
📊 MODEL EVALUATION REPORT
================================================================================

🏆 OVERALL SCORES
--------------------------------------------------------------------------------
Claude Opus 4.6                | Score:  97.0 | Latency:  1200ms | Tokens: 1456
Claude Sonnet 4.5              | Score:  95.0 | Latency:   950ms | Tokens: 1234
deepseek-coder-v2:16b          | Score:  90.0 | Latency:  3456ms | Tokens: 2567
qwen2.5-coder:14b              | Score:  88.0 | Latency:  3157ms | Tokens: 2345
Claude Haiku 4.5               | Score:  85.0 | Latency:   600ms | Tokens:  987
qwen2.5:14b                    | Score:  82.0 | Latency:  2987ms | Tokens: 2123

📋 TEST BREAKDOWN
--------------------------------------------------------------------------------

Code Generation:
  ✅ Claude Opus 4.6           100.0/100 (1234ms)
  ✅ qwen2.5-coder:14b         100.0/100 (2987ms)
  ✅ deepseek-coder-v2:16b     100.0/100 (3123ms)
  ✅ Claude Sonnet 4.5         100.0/100 (1100ms)
  ✅ Claude Haiku 4.5           95.0/100 (654ms)
  ✅ qwen2.5:14b                85.0/100 (2876ms)

Logical Reasoning:
  ✅ Claude Opus 4.6           100.0/100 (1156ms)
  ✅ Claude Sonnet 4.5         100.0/100 (987ms)
  ✅ deepseek-coder-v2:16b      85.0/100 (3456ms)
  ✅ qwen2.5-coder:14b          80.0/100 (2345ms)
  ✅ Claude Haiku 4.5           80.0/100 (543ms)
  ✅ qwen2.5:14b                75.0/100 (2543ms)

Speed Test:
  ✅ Claude Haiku 4.5          100.0/100 (600ms)
  ✅ Claude Sonnet 4.5          80.0/100 (950ms)
  ✅ Claude Opus 4.6            60.0/100 (1200ms)
  ✅ qwen2.5:14b                40.0/100 (2987ms)
  ✅ qwen2.5-coder:14b          40.0/100 (3157ms)
  ✅ deepseek-coder-v2:16b      40.0/100 (3456ms)

🎯 RECOMMENDATIONS
--------------------------------------------------------------------------------
Best Overall:     Claude Opus 4.6 (97.0/100)
Fastest:          Claude Haiku 4.5 (600ms)
Most Efficient:   Claude Haiku 4.5
Best Free:        deepseek-coder-v2:16b (90.0/100)

💡 SUGGESTED CONFIGURATION:
- PM Agent:       Claude Sonnet 4.5 (best reasoning)
- Coder Agent:    qwen2.5-coder:14b (free, great code)
- Security Agent: qwen2.5:14b (free, good reasoning)
- Fallback:       Claude Haiku 4.5 (fast, cheap)

💰 ESTIMATED MONTHLY COST:
- All Claude:     ~$900/month
- Hybrid (above): ~$150/month
- All Ollama:     $0/month (GPU VPS: $216-360)

================================================================================
```

---

## 🎊 Summary

**You now have:**

✅ **Model evaluator** that tests 5 key capabilities
✅ **Automatic detection** of Anthropic + Ollama models
✅ **Comparison reports** showing best model for each task
✅ **Cost analysis** to optimize spending
✅ **JSON export** for further analysis
✅ **Custom test framework** to add your own tests

**Use it to:**

- Find best model for your use case
- Compare cloud vs local models
- Optimize cost while maintaining quality
- Track model improvements over time

**Run it:**

```bash
python3 model-evaluator.py
```

🧪 **Start evaluating!** ✨
