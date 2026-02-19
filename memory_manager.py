"""
Mem0-inspired persistent memory system for OpenClaw agents.

Stores structured memories with tags, importance scoring, and keyword search.
Provides context injection for agent system prompts.
"""

import json
import os
import re
import uuid
import threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

MEMORY_DIR = Path("/tmp/openclaw_memories")
INDEX_FILE = MEMORY_DIR / "index.json"

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

    def _score(self, memory_id, query_tokens):
        """TF-IDF-like relevance score: tag matches weighted 3x, content matches 1x."""
        entry = self._index.get(memory_id)
        if not entry:
            return 0.0
        tag_tokens = set()
        for tag in entry.get("tags", []):
            tag_tokens.update(self._tokenize(tag))
        preview_tokens = Counter(self._tokenize(entry.get("content_preview", "")))
        score = 0.0
        for qt in query_tokens:
            if qt in tag_tokens:
                score += 3.0
            score += preview_tokens.get(qt, 0) * 1.0
        importance = entry.get("importance", 5)
        score *= (1 + importance / 20.0)
        return score

    def search_memories(self, query, limit=10):
        """Keyword search across all memories, ranked by relevance."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        scored = []
        with self._lock:
            for mid in self._index:
                s = self._score(mid, query_tokens)
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
