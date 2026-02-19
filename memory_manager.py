"""
Mem0-inspired persistent memory system for OpenClaw agents.

Stores structured memories with tags, importance scoring, and TF-IDF search.
Provides context injection for agent system prompts.
Auto-extracts lessons learned from failed jobs and completed job results.
"""

import json
import math
import os
import re
import uuid
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

MEMORY_DIR = Path("/tmp/openclaw_memories")
INDEX_FILE = MEMORY_DIR / "index.json"
JOBS_FILE = Path("/tmp/openclaw_jobs/jobs.jsonl")

_lock = threading.Lock()
_instance = None


class MemoryManager:
    def __init__(self, memory_dir=MEMORY_DIR):
        self.memory_dir = Path(memory_dir)
        self.index_file = self.memory_dir / "index.json"
        self._lock = threading.Lock()
        self._index = {}
        self._ensure_dir()
        self._load_index()

    def _ensure_dir(self):
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self):
        with self._lock:
            if self.index_file.exists():
                try:
                    self._index = json.loads(self.index_file.read_text())
                except (json.JSONDecodeError, OSError):
                    self._index = {}
            else:
                self._index = {}

    def _save_index(self):
        self.index_file.write_text(json.dumps(self._index, indent=2, default=str))

    def _save_memory(self, memory):
        path = self.memory_dir / f"{memory['id']}.json"
        path.write_text(json.dumps(memory, indent=2, default=str))

    def _load_memory(self, memory_id):
        path = self.memory_dir / f"{memory_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def add_memory(self, content, tags=None, source="conversation",
                   agent_id="overseer", importance=5):
        """Save a fact, decision, or preference as a persistent memory."""
        if tags is None:
            tags = []
        now = datetime.utcnow().isoformat()
        memory = {
            "id": uuid.uuid4().hex[:12],
            "content": content.strip(),
            "tags": [t.lower().strip() for t in tags],
            "source": source,
            "agent_id": agent_id,
            "importance": max(1, min(10, importance)),
            "created_at": now,
            "accessed_at": now,
            "access_count": 0,
        }
        with self._lock:
            self._index[memory["id"]] = {
                "content_preview": content[:120],
                "tags": memory["tags"],
                "agent_id": agent_id,
                "importance": memory["importance"],
                "created_at": now,
                "accessed_at": now,
                "access_count": 0,
            }
            self._save_memory(memory)
            self._save_index()
        return memory["id"]

    def _touch(self, memory_id):
        """Update accessed_at and access_count on a memory."""
        now = datetime.utcnow().isoformat()
        if memory_id in self._index:
            self._index[memory_id]["accessed_at"] = now
            self._index[memory_id]["access_count"] = self._index[memory_id].get("access_count", 0) + 1
        mem = self._load_memory(memory_id)
        if mem:
            mem["accessed_at"] = now
            mem["access_count"] = mem.get("access_count", 0) + 1
            self._save_memory(mem)

    def _tokenize(self, text):
        """Split text into lowercase word tokens."""
        return re.findall(r"[a-z0-9]+", text.lower())

    def _build_idf(self):
        """Compute IDF (inverse document frequency) for all tokens across all memories."""
        doc_count = len(self._index)
        if doc_count == 0:
            return {}
        # Count how many documents contain each token
        doc_freq = Counter()
        for entry in self._index.values():
            tokens_in_doc = set()
            for tag in entry.get("tags", []):
                tokens_in_doc.update(self._tokenize(tag))
            tokens_in_doc.update(self._tokenize(entry.get("content_preview", "")))
            for t in tokens_in_doc:
                doc_freq[t] += 1
        # IDF = log(N / df) + 1  (smoothed)
        idf = {}
        for token, df in doc_freq.items():
            idf[token] = math.log(doc_count / df) + 1.0
        return idf

    def _score(self, memory_id, query_tokens, idf=None):
        """TF-IDF relevance score with tag boost and importance weighting.

        Tags get 3x weight. IDF down-weights common tokens (like 'the', 'code').
        Importance and recency provide additional boosting.
        """
        entry = self._index.get(memory_id)
        if not entry:
            return 0.0

        tag_tokens = set()
        for tag in entry.get("tags", []):
            tag_tokens.update(self._tokenize(tag))
        preview_tokens = Counter(self._tokenize(entry.get("content_preview", "")))

        score = 0.0
        for qt in query_tokens:
            token_idf = idf.get(qt, 1.0) if idf else 1.0
            # Tag match: TF=1 (binary), weight 3x
            if qt in tag_tokens:
                score += 3.0 * token_idf
            # Content match: TF from counter, weight 1x
            tf = preview_tokens.get(qt, 0)
            if tf > 0:
                # Sublinear TF: 1 + log(tf)
                score += (1.0 + math.log(tf)) * token_idf

        # Importance boost (1.0 to 1.5)
        importance = entry.get("importance", 5)
        score *= (1.0 + importance / 20.0)

        # Recency boost: memories accessed in last 7 days get up to 1.2x
        accessed = entry.get("accessed_at", "")
        if accessed:
            try:
                acc_dt = datetime.fromisoformat(accessed)
                days_ago = (datetime.utcnow() - acc_dt).total_seconds() / 86400
                if days_ago < 7:
                    score *= (1.0 + 0.2 * (1.0 - days_ago / 7.0))
            except (ValueError, TypeError):
                pass

        # Lessons learned get a slight boost for relevance
        if "lessons-learned" in entry.get("tags", []):
            score *= 1.15

        return score

    def search_memories(self, query, limit=10):
        """TF-IDF keyword search across all memories, ranked by relevance."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        scored = []
        with self._lock:
            idf = self._build_idf()
            for mid in self._index:
                s = self._score(mid, query_tokens, idf=idf)
                if s > 0:
                    scored.append((s, mid))
        scored.sort(key=lambda x: -x[0])
        results = []
        for _, mid in scored[:limit]:
            mem = self._load_memory(mid)
            if mem:
                self._touch(mid)
                results.append(mem)
        if results:
            with self._lock:
                self._save_index()
        return results

    def get_recent(self, limit=20):
        """Return the most recently accessed memories."""
        with self._lock:
            sorted_ids = sorted(
                self._index.keys(),
                key=lambda mid: self._index[mid].get("accessed_at", ""),
                reverse=True,
            )
        results = []
        for mid in sorted_ids[:limit]:
            mem = self._load_memory(mid)
            if mem:
                results.append(mem)
        return results

    def get_by_tag(self, tag):
        """Return all memories containing a specific tag."""
        tag = tag.lower().strip()
        results = []
        with self._lock:
            for mid, entry in self._index.items():
                if tag in entry.get("tags", []):
                    mem = self._load_memory(mid)
                    if mem:
                        results.append(mem)
        return results

    def get_context_for_prompt(self, query, max_tokens=2000):
        """Return a formatted string of relevant memories for system prompt injection."""
        memories = self.search_memories(query, limit=20)
        if not memories:
            return ""
        lines = ["## Relevant Memories", ""]
        char_budget = max_tokens * 4  # rough chars-to-tokens
        used = 0
        for mem in memories:
            entry = (
                f"- [{', '.join(mem['tags'])}] "
                f"(importance:{mem['importance']}, agent:{mem['agent_id']}) "
                f"{mem['content']}"
            )
            if used + len(entry) > char_budget:
                break
            lines.append(entry)
            used += len(entry)
        return "\n".join(lines)

    # ---- Auto-extraction heuristics ----

    _SIGNAL_WORDS_HIGH = re.compile(
        r"\b(always|never|prefer|remember|must|require|important|critical)\b", re.I
    )
    _PROJECT_NAMES = re.compile(
        r"\b(openclaw|barber[\s-]?crm|prestresscalc|delhi[\s-]?palace|concrete[\s-]?canoe|moltbot)\b", re.I
    )
    _NUMBER_DATE = re.compile(
        r"(\$[\d,.]+|\b\d{4}[-/]\d{2}[-/]\d{2}\b|\b\d+%|\b\d{2,}\b)"
    )
    _URL = re.compile(r"https?://[^\s<>\"]+")

    def auto_extract_memories(self, conversation_messages):
        """Scan conversation messages for facts worth remembering.

        Args:
            conversation_messages: list of dicts with at least a "content" key,
                optionally "role" and "agent_id".

        Returns:
            list of memory IDs created.
        """
        created = []
        for msg in conversation_messages:
            content = msg.get("content", "")
            agent_id = msg.get("agent_id", "overseer")
            role = msg.get("role", "user")
            if not content or len(content) < 10:
                continue
            sentences = re.split(r"[.!?\n]+", content)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 10:
                    continue
                tags = [role]
                importance = 3

                if self._SIGNAL_WORDS_HIGH.search(sentence):
                    importance = max(importance, 8)
                    tags.append("preference")

                pm = self._PROJECT_NAMES.search(sentence)
                if pm:
                    importance = max(importance, 6)
                    tags.append(pm.group(1).lower().replace(" ", "-"))

                if self._NUMBER_DATE.search(sentence):
                    importance = max(importance, 5)
                    tags.append("data")

                if self._URL.search(sentence):
                    importance = max(importance, 4)
                    tags.append("reference")

                # Only store if something notable was detected
                if importance >= 4:
                    mid = self.add_memory(
                        sentence,
                        tags=tags,
                        source="auto_extract",
                        agent_id=agent_id,
                        importance=importance,
                    )
                    created.append(mid)
        return created

    # ---- Auto-extraction from completed job results ----

    def extract_from_job_result(self, job: dict) -> list:
        """Extract memories from a completed job's results.

        Captures: which agent handled it, task description, outcome,
        cost, and any error patterns. Returns list of memory IDs created.
        """
        created = []
        job_id = job.get("id", "unknown")
        status = job.get("status", "")
        task = job.get("task", job.get("description", ""))
        agent = job.get("agent", job.get("agent_id", "unknown"))
        project = job.get("project", "openclaw")

        if not task:
            return created

        if status in ("done", "merged", "approved", "completed"):
            # Successful job -> remember the task-agent-project pattern
            content = (
                f"Job {job_id} completed successfully: '{task}' "
                f"handled by {agent} for project {project}."
            )
            pr_url = job.get("pr_url")
            if pr_url:
                content += f" PR: {pr_url}"

            mid = self.add_memory(
                content,
                tags=["job-result", "success", project, agent],
                source="job_completion",
                agent_id=agent,
                importance=5,
            )
            created.append(mid)

        elif status == "failed":
            # Failed job -> capture as lesson learned
            reason = job.get("failure_reason", job.get("error", "unknown error"))
            created.extend(
                self.record_lesson_learned(
                    task=task,
                    error=reason,
                    agent_id=agent,
                    project=project,
                    job_id=job_id,
                )
            )

        return created

    def scan_jobs_for_extraction(self) -> list:
        """Scan the jobs file for completed/failed jobs not yet extracted.

        Uses a marker file to track which jobs have been processed.
        Returns list of memory IDs created.
        """
        if not JOBS_FILE.exists():
            return []

        marker_file = self.memory_dir / "extracted_jobs.json"
        extracted_ids = set()
        if marker_file.exists():
            try:
                extracted_ids = set(json.loads(marker_file.read_text()))
            except (json.JSONDecodeError, OSError):
                pass

        created = []
        newly_extracted = []

        try:
            with open(JOBS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        job = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    job_id = job.get("id", "")
                    if not job_id or job_id in extracted_ids:
                        continue
                    status = job.get("status", "")
                    if status in ("done", "merged", "approved", "completed", "failed"):
                        ids = self.extract_from_job_result(job)
                        created.extend(ids)
                        newly_extracted.append(job_id)
        except OSError:
            pass

        if newly_extracted:
            extracted_ids.update(newly_extracted)
            try:
                marker_file.write_text(json.dumps(list(extracted_ids)))
            except OSError:
                pass

        return created

    # ---- Lessons learned from failures ----

    def record_lesson_learned(self, task: str, error: str, agent_id: str = "system",
                              project: str = "openclaw", job_id: str = "") -> list:
        """Record a lesson learned from a failure.

        Captures the task, error, and creates a high-importance memory
        tagged as 'lessons-learned' so future routing can avoid the same mistake.
        """
        created = []

        # Core lesson
        content = (
            f"LESSON LEARNED (job {job_id}): Task '{task}' failed on agent {agent_id}. "
            f"Error: {error}"
        )
        mid = self.add_memory(
            content,
            tags=["lessons-learned", "failure", project, agent_id],
            source="lesson_learned",
            agent_id=agent_id,
            importance=7,  # High importance so it surfaces in future searches
        )
        created.append(mid)

        # Check for repeated failure pattern
        existing = self.search_memories(f"LESSON LEARNED {task} {agent_id}", limit=5)
        similar_failures = [
            m for m in existing
            if "lessons-learned" in m.get("tags", [])
            and m.get("id") != mid
            and agent_id in m.get("content", "")
        ]

        if len(similar_failures) >= 1:
            # Pattern detected: same agent keeps failing on similar tasks
            pattern_content = (
                f"PATTERN: Agent {agent_id} has failed {len(similar_failures) + 1}x "
                f"on similar tasks (latest: '{task}'). "
                f"Consider routing to a different agent or escalating to Opus."
            )
            pattern_mid = self.add_memory(
                pattern_content,
                tags=["lessons-learned", "failure-pattern", project, agent_id],
                source="pattern_detection",
                agent_id="system",
                importance=9,  # Very high importance
            )
            created.append(pattern_mid)

        return created

    def get_lessons_learned(self, limit=20) -> list:
        """Return all lessons learned, sorted by importance and recency."""
        return self.get_by_tag("lessons-learned")[:limit]

    def prune_old(self, days=30):
        """Remove memories not accessed in `days` days with importance < 3."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        to_remove = []
        with self._lock:
            for mid, entry in self._index.items():
                if entry.get("importance", 5) < 3 and entry.get("accessed_at", "") < cutoff:
                    to_remove.append(mid)
            for mid in to_remove:
                del self._index[mid]
                path = self.memory_dir / f"{mid}.json"
                if path.exists():
                    path.unlink()
            if to_remove:
                self._save_index()
        return len(to_remove)

    def export_to_markdown(self):
        """Dump all memories as a readable markdown string."""
        lines = [
            "# OpenClaw Memory Export",
            f"Generated: {datetime.utcnow().isoformat()}",
            f"Total memories: {len(self._index)}",
            "",
        ]
        all_mems = []
        for mid in self._index:
            mem = self._load_memory(mid)
            if mem:
                all_mems.append(mem)
        all_mems.sort(key=lambda m: m.get("importance", 0), reverse=True)

        by_tag = {}
        for mem in all_mems:
            for tag in mem.get("tags", ["untagged"]):
                by_tag.setdefault(tag, []).append(mem)

        for tag in sorted(by_tag.keys()):
            lines.append(f"## Tag: {tag}")
            lines.append("")
            for mem in by_tag[tag]:
                lines.append(
                    f"- **[{mem['importance']}/10]** {mem['content'][:200]}"
                    f"  _(agent: {mem['agent_id']}, accessed: {mem.get('access_count', 0)}x, "
                    f"created: {mem['created_at'][:10]})_"
                )
            lines.append("")
        return "\n".join(lines)

    def count(self):
        """Return total number of memories."""
        return len(self._index)


# ---- Singleton & integration helpers ----

def init_memory_manager(memory_dir=MEMORY_DIR):
    """Initialize the global MemoryManager singleton."""
    global _instance
    with _lock:
        _instance = MemoryManager(memory_dir=memory_dir)
    return _instance


def get_memory_manager():
    """Get or create the global MemoryManager singleton."""
    global _instance
    if _instance is None:
        return init_memory_manager()
    return _instance


def memory_context_for_agent(agent_id, query):
    """Return relevant memories formatted for system prompt injection.

    Filters by agent_id plus general memories, then formats
    for inclusion in a system prompt.
    """
    mm = get_memory_manager()
    all_results = mm.search_memories(query, limit=30)
    filtered = [
        m for m in all_results
        if m.get("agent_id") in (agent_id, "overseer", "system")
    ][:15]
    if not filtered:
        return ""
    lines = [f"## Memory Context (agent: {agent_id})", ""]
    for mem in filtered:
        tags_str = ", ".join(mem.get("tags", []))
        lines.append(f"- [{tags_str}] {mem['content']}")
    return "\n".join(lines)
