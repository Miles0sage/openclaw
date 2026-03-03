# Semantic Memory System — OpenClaw v3.7+

## Overview

The OpenClaw semantic memory system provides **meaning-based search** across agent memories using TF-IDF vectorization. Unlike keyword matching, semantic search finds relevant facts even when the query uses different words.

### Key Features

- **Semantic Search**: Finds memories by meaning, not just keywords
- **Lightweight**: Uses scikit-learn TF-IDF (no external vector DB required)
- **Auto-Indexing**: Caches index to disk for fast startup
- **Memory Compaction**: Auto-saves critical facts before context cleanup
- **Multi-Source Indexing**: Indexes memories.jsonl, MEMORY.md files, and daily logs

---

## Architecture

```
┌─────────────────────────────────────────┐
│        Agent Tools (agent_tools.py)    │
│                                         │
│  search_memory()      ──┬──→ keyword   │
│                         └──→ semantic  │
│  rebuild_semantic_index()              │
│  flush_memory_before_compaction()      │
└─────────────────────────────────────────┘
            ↓
┌──────────────────────────────────────────────────┐
│     Semantic Memory Index (semantic_memory.py)  │
│                                                  │
│  - TF-IDF vectorizer (5000 features)            │
│  - Cosine similarity search                      │
│  - Disk cache (semantic_index.pkl)               │
│  - 968 documents indexed                         │
│  - Auto-rebuild on source change                 │
└──────────────────────────────────────────────────┘
            ↓
┌──────────────────────────────────────────────────┐
│      Memory Compaction (memory_compaction.py)   │
│                                                  │
│  - Detects context >50% usage                    │
│  - Extracts important facts                      │
│  - Flushes to MEMORY.md                          │
│  - Prevents loss of critical decisions           │
└──────────────────────────────────────────────────┘
            ↓
┌──────────────────────────────────────────────────┐
│    Memory Storage                                │
│                                                  │
│  ✓ memories.jsonl (27 records)                   │
│  ✓ MEMORY.md topic files (51 files)              │
│  ✓ Daily session logs (optional)                 │
│  ✓ semantic_index.pkl (cache)                    │
│  ✓ semantic_metadata.json (index info)           │
└──────────────────────────────────────────────────┘
```

---

## Usage

### 1. Semantic Search

When an agent searches memory, it automatically tries semantic search first:

```python
# In agent_tools.py handler
result = _search_memory("deployment pipeline optimization", limit=5)

# Returns semantic matches by meaning:
# Found 3 semantic matches:
# [2456a857] (imp=7, sim=21%) memory_md:moltbot-agency-dashboard.md: Deployment Details
# [15424622] (imp=7, sim=20%) memory_md:PRODUCTION-AGENCY-RESEARCH.md: Deployment Architecture
```

**Similarity Score**: 0-100% indicates how close a match is to the query meaning.

### 2. Rebuild Index

After adding many new memories or memory files:

```python
from semantic_memory import rebuild_index
rebuild_index()
```

Or via agent tool:

```json
{
  "tool": "rebuild_semantic_index",
  "input": {}
}
```

### 3. Memory Compaction

When Claude Code reaches 50% context usage, important facts can be flushed:

```python
from memory_compaction import flush_pending

items = [
    "Decision: Moving to OAuth2 instead of custom JWT",
    "Critical: Database backup needed before migration",
    "Learning: Session tokens should be short-lived (15 min)"
]

result = flush_pending(items)
# Result: {'flushed_count': 3, 'file': '/root/.claude/projects/-root/memory/MEMORY.md'}
```

Or via agent tool:

```json
{
  "tool": "flush_memory_before_compaction",
  "input": {
    "items": [
      "Decision: Moving to OAuth2 instead of custom JWT",
      "Critical: Database backup needed before migration"
    ]
  }
}
```

---

## How It Works

### Semantic Search (TF-IDF)

1. **Index Building**:
   - Reads memories.jsonl (27 records)
   - Reads MEMORY.md topic files (968 document sections)
   - Reads daily logs (if available)
   - Vectorizes all text using TF-IDF (Term Frequency-Inverse Document Frequency)
   - Builds sparse matrix (968 docs × 5000 features)
   - Caches to `semantic_index.pkl`

2. **Search Process**:

   ```
   Query: "deployment pipeline optimization"
            ↓
   Vectorize query using same TF-IDF model
            ↓
   Compute cosine similarity: query_vec · doc_vec / (||query_vec|| × ||doc_vec||)
            ↓
   Sort by similarity score (0-1)
            ↓
   Return top 5 matches with score and metadata
   ```

3. **Fallback Logic**:
   - If semantic search fails → keyword search
   - If keyword search fails → Supabase query
   - If Supabase fails → JSONL fallback

### Memory Compaction (Auto-Save)

When context >50%:

1. Extract facts using keyword patterns:
   - `decision:` → importance 8
   - `critical:` → importance 9
   - `learning:` → importance 7
   - `TODO:` → importance 6
   - etc.

2. Append to MEMORY.md under "Auto-extracted facts" section

3. Log compaction event to `.compaction_log.json`

---

## Performance

### Index Statistics

- **Total Documents**: 968
- **Feature Dimension**: 5000 (TF-IDF features)
- **Sparse Matrix Size**: 968 × 5000 (~500KB on disk)
- **Build Time**: ~2 seconds
- **Search Time**: <50ms per query
- **Cache Location**: `/root/openclaw/data/semantic_index.pkl`

### Memory Usage

- Vectorizer + matrix in memory: ~50MB
- Index reload time: <1 second

### When Index Rebuilds

- On startup (if source files changed)
- When agents call `rebuild_semantic_index()`
- On Stop hook (settings.json)

---

## Integration Points

### With Agent Tools

The system is integrated into agent_tools.py three ways:

1. **`search_memory(query, limit=5)`**:
   - Tries semantic search first
   - Falls back to keyword search
   - Returns best matches with scores

2. **`rebuild_semantic_index()`**:
   - Force rebuild of TF-IDF index
   - Used after bulk memory additions

3. **`flush_memory_before_compaction(items)`**:
   - Saves pending facts to MEMORY.md
   - Called before context compaction

### With Claude Code Hooks

In `/root/.claude/settings.json`, the Stop hook rebuilds index:

```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "command",
      "command": "python3 /root/openclaw/semantic_memory.py"
    }
  ]
}
```

### With Memory Compaction

Integration point: `_search_memory()` in agent_tools.py calls semantic search, preserving context quality.

---

## File Structure

```
/root/openclaw/
├── semantic_memory.py          (968 doc index, TF-IDF, search)
├── memory_compaction.py        (auto-save facts before compaction)
├── agent_tools.py              (integrated search/rebuild/flush tools)
└── data/
    ├── memories.jsonl          (27 user/system memories)
    ├── semantic_index.pkl      (cached vectorizer + matrix)
    ├── semantic_metadata.json  (index info, doc list)
    └── .compaction_log.json    (compaction events)

/root/.claude/projects/-root/memory/
├── MEMORY.md                   (main index, 51 topics)
├── business-strategy.md
├── openclaw-architecture.md
├── prestresscalc-status.md
├── projects.md
└── ... (46 more .md files)
```

---

## Configuration

### Tuning Search Parameters

In `semantic_memory.py`:

```python
# Adjust vectorizer parameters
self.vectorizer = TfidfVectorizer(
    max_features=5000,        # Reduce to 1000 for faster search
    stop_words="english",     # Language of content
    lowercase=True,
    ngram_range=(1, 2),       # (1,2) = unigrams + bigrams
    min_df=1,                 # Min docs for a feature
    max_df=0.95               # Max docs for a feature (ignore common words)
)

# Adjust minimum similarity threshold
min_score=0.1                 # 10% = very liberal, 0.3 = strict
```

### Customizing Fact Extraction

In `memory_compaction.py`:

```python
# Edit these patterns to detect different fact types
patterns = [
    ("decision:", 8),
    ("critical:", 9),
    ("learning:", 7),
    ("TODO:", 6),
    ("BUG:", 8),  # Add custom patterns
    ("ARCHITECTURE:", 8),
]
```

---

## Troubleshooting

### Index Not Rebuilding

**Problem**: Semantic search returns no results
**Solution**:

```python
from semantic_memory import rebuild_index
rebuild_index()
```

### Search Returns Only Keyword Matches

**Problem**: TF-IDF not working
**Solution**: Check scikit-learn is installed:

```bash
python3 -c "import sklearn; print(sklearn.__version__)"
# Should show version >= 1.0
```

### Memory Compaction Not Working

**Problem**: Facts not appearing in MEMORY.md
**Solution**: Check file permissions:

```bash
ls -la /root/.claude/projects/-root/memory/MEMORY.md
# Should be writable by current user
```

### High Memory Usage

**Problem**: Index takes too much RAM
**Solution**: Reduce max_features in TfidfVectorizer:

```python
max_features=2000  # Instead of 5000
```

---

## Best Practices

1. **Regular Index Rebuilds**: Call `rebuild_semantic_index()` weekly
2. **Memory Compaction**: Use `flush_pending()` before long breaks
3. **Fact Extraction**: Keep decision summaries <200 chars
4. **Tag Management**: Use consistent tags (project, component, issue-type)
5. **Importance Levels**:
   - 9: Critical decisions (go/no-go, security)
   - 8: Important milestones (deployments, API changes)
   - 7: Key learnings (patterns, debugging lessons)
   - 6: Implementation details (TODOs, architecture notes)
   - 5: Reference information (defaults, parameters)
   - 1-4: Minor details

---

## Future Improvements

- [ ] Embeddings API support (OpenAI, Anthropic) for better semantic search
- [ ] Hierarchical search (search within projects or tags)
- [ ] Multi-modal search (code + markdown)
- [ ] Automatic importance scoring
- [ ] Cross-memory linking (similar facts detected automatically)
- [ ] Memory summarization before archival

---

## Related Files

- [/root/openclaw/CLAUDE.md](./CLAUDE.md) — Agent souls & routing
- [/root/.claude/projects/-root/memory/MEMORY.md](../../../.claude/projects/-root/memory/MEMORY.md) — Master memory index
- [error-patterns.md](../../../.claude/projects/-root/memory/error-patterns.md) — Hard-won debugging lessons
