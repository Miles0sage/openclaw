"""
Agent Router for OpenClaw - Intelligently routes queries to best agent
Based on keyword patterns and intent classification from complexity_classifier.py
Routes queries to: project_manager, coder_agent, or hacker_agent
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import json
import os


@dataclass
class RoutingDecision:
    agentId: str  # "project_manager" | "coder_agent" | "hacker_agent"
    confidence: float  # 0-1
    reason: str
    intent: str
    keywords: List[str]


class AgentRouter:
    """Intelligent router that selects best agent based on query content"""

    # Agent specifications
    AGENTS = {
        "project_manager": {
            "id": "project_manager",
            "name": "Cybershield PM",
            "skills": [
                "task_decomposition", "timeline_estimation", "quality_assurance",
                "client_communication", "team_coordination", "agent_coordination",
                "workflow_optimization"
            ]
        },
        "coder_agent": {
            "id": "coder_agent",
            "name": "CodeGen Pro",
            "skills": [
                "nextjs", "fastapi", "typescript", "tailwind", "postgresql",
                "supabase", "clean_code", "testing", "code_analysis",
                "function_calling", "git_automation"
            ]
        },
        "hacker_agent": {
            "id": "hacker_agent",
            "name": "Pentest AI",
            "skills": [
                "security_scanning", "vulnerability_assessment", "penetration_testing",
                "owasp", "security_best_practices", "threat_modeling",
                "secure_architecture"
            ]
        }
    }

    # Keywords for intent classification (from config or defaults)
    SECURITY_KEYWORDS = [
        "security", "vulnerability", "exploit", "penetration", "audit",
        "xss", "csrf", "injection", "pentest", "hack", "breach",
        "secure", "threat", "attack", "threat_modeling", "risk",
        "malware", "payload", "sanitize", "encrypt", "cryptography",
        "authentication", "authorization", "access control", "sql injection"
    ]

    DEVELOPMENT_KEYWORDS = [
        "code", "implement", "function", "fix", "bug", "api", "endpoint",
        "build", "typescript", "fastapi", "python", "javascript", "react",
        "nextjs", "database", "query", "schema", "testing", "test",
        "deploy", "deployment", "frontend", "backend", "full-stack",
        "refactor", "refactoring", "clean_code", "git", "repository",
        "json", "yaml", "xml", "rest", "graphql", "websocket"
    ]

    PLANNING_KEYWORDS = [
        "plan", "timeline", "schedule", "roadmap", "strategy", "architecture",
        "design", "approach", "workflow", "process", "milestone", "deadline",
        "estimate", "estimation", "breakdown", "decompose", "coordinate",
        "manage", "organize", "project", "phase", "sprint", "agile"
    ]

    def __init__(self, config_path: str = "/root/openclaw/config.json"):
        """Initialize router with optional config file"""
        self.config = {}
        self._load_config(config_path)
        self._update_keywords_from_config()

    def _load_config(self, config_path: str) -> None:
        """Load configuration from config.json if available"""
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    self.config = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config from {config_path}: {e}")
            self.config = {}

    def _update_keywords_from_config(self) -> None:
        """Update keywords from config.json routing section if available"""
        try:
            routing_config = self.config.get("routing", {}).get("keywords", {})
            if routing_config:
                self.SECURITY_KEYWORDS = routing_config.get("security", self.SECURITY_KEYWORDS)
                self.DEVELOPMENT_KEYWORDS = routing_config.get("development", self.DEVELOPMENT_KEYWORDS)
                self.PLANNING_KEYWORDS = routing_config.get("planning", self.PLANNING_KEYWORDS)
        except Exception:
            pass  # Use defaults if config parsing fails

    def select_agent(self, query: str, session_state: Optional[Dict] = None) -> Dict:
        """
        Route query to best agent based on intent and keywords.
        Returns: {"agentId": "...", "confidence": 0.9, "reason": "...", "intent": "..."}
        """
        normalized_query = query.lower()

        # 1. Classify intent
        intent = self._classify_intent(normalized_query)

        # 2. Extract keywords
        keywords = self._extract_keywords(normalized_query)

        # 3. Score agents
        scores = self._score_agents(intent, keywords)

        # 4. Get best agent
        agent_id, confidence = self._get_best_agent(scores)

        # 5. Build reason
        reason = self._build_reason(intent, keywords, agent_id, confidence)

        return {
            "agentId": agent_id,
            "confidence": confidence,
            "reason": reason,
            "intent": intent,
            "keywords": keywords
        }

    def _classify_intent(self, query: str) -> str:
        """
        Classify query intent as: security_audit, development, planning, or general
        """
        security_count = sum(1 for kw in self.SECURITY_KEYWORDS if self.match_keyword(query, kw))
        dev_count = sum(1 for kw in self.DEVELOPMENT_KEYWORDS if self.match_keyword(query, kw))
        planning_count = sum(1 for kw in self.PLANNING_KEYWORDS if self.match_keyword(query, kw))

        if security_count > 0 and security_count >= dev_count and security_count >= planning_count:
            return "security_audit"
        elif dev_count > 0 and dev_count >= planning_count:
            return "development"
        elif planning_count > 0:
            return "planning"
        else:
            return "general"

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract all matching keywords from query"""
        keywords = []
        for kw in self.SECURITY_KEYWORDS + self.DEVELOPMENT_KEYWORDS + self.PLANNING_KEYWORDS:
            if self.match_keyword(query, kw):
                keywords.append(kw)
        return keywords

    def _score_agents(self, intent: str, keywords: List[str]) -> Dict[str, float]:
        """
        Score each agent 0-1 for this query.
        Weights: intent_match (60%) + skill_match (30%) + availability (10%)
        """
        scores = {}

        for agent_id, agent_config in self.AGENTS.items():
            intent_score = self._compute_intent_match(agent_id, intent)
            skill_score = self._compute_skill_match(agent_id, keywords)
            availability_score = 1.0  # Assume all available for now

            # Weighted combination
            total_score = (
                intent_score * 0.6 +
                skill_score * 0.3 +
                availability_score * 0.1
            )
            scores[agent_id] = max(0.0, min(1.0, total_score))

        return scores

    def _compute_intent_match(self, agent_id: str, intent: str) -> float:
        """
        Compute how well an agent matches the detected intent.
        Returns 0-1 float.
        """
        if intent == "general":
            # General queries routed to PM
            return 1.0 if agent_id == "project_manager" else 0.3

        elif intent == "security_audit":
            if agent_id == "hacker_agent":
                return 1.0
            elif agent_id == "coder_agent":
                return 0.5
            else:
                return 0.2

        elif intent == "development":
            if agent_id == "coder_agent":
                return 1.0
            elif agent_id == "hacker_agent":
                return 0.4  # Security considerations in dev
            else:
                return 0.3

        elif intent == "planning":
            if agent_id == "project_manager":
                return 1.0
            elif agent_id == "coder_agent":
                return 0.4
            else:
                return 0.2

        return 0.3

    def _compute_skill_match(self, agent_id: str, keywords: List[str]) -> float:
        """
        Compute how many keywords match agent's skills.
        Returns 0-1 float based on skill coverage.
        """
        if not keywords:
            return 0.0

        agent_config = self.AGENTS[agent_id]
        skills = agent_config["skills"]

        matches = 0
        for keyword in keywords:
            # Check if keyword matches any skill (fuzzy match on skill names)
            for skill in skills:
                # Direct match or partial match
                if keyword in skill or skill in keyword:
                    matches += 1
                    break

        # Return percentage of keywords matched, capped at 1.0
        return min(1.0, matches / len(keywords))

    def _get_best_agent(self, scores: Dict[str, float]) -> Tuple[str, float]:
        """
        Select best agent from scores.
        Returns (agent_id, confidence)
        """
        if not scores:
            # Fallback to PM
            return "project_manager", 0.5

        best_agent = max(scores.items(), key=lambda x: x[1])
        return best_agent[0], round(best_agent[1] * 100) / 100

    def _build_reason(self, intent: str, keywords: List[str], agent_id: str, confidence: float) -> str:
        """Build human-readable reason for routing decision"""
        agent_name = self.AGENTS[agent_id]["name"]
        intent_desc = {
            "security_audit": "Security audit requested",
            "development": "Development task",
            "planning": "Planning/coordination task",
            "general": "General inquiry"
        }.get(intent, "Query matched")

        if keywords:
            keyword_str = ", ".join(keywords[:3])  # Show top 3 keywords
            if len(keywords) > 3:
                keyword_str += f" +{len(keywords) - 3} more"
            return f"{intent_desc} with keywords [{keyword_str}] → {agent_name} (confidence: {confidence:.0%})"
        else:
            return f"{intent_desc} (no keywords) → {agent_name} (confidence: {confidence:.0%})"

    def match_keyword(self, query: str, keyword: str) -> bool:
        """
        Match keyword with word-boundary awareness.
        Reuses pattern from complexity_classifier.py
        """
        if " " in keyword:
            return keyword in query
        if len(keyword) <= 3:
            return bool(re.search(rf"\b{re.escape(keyword)}\b", query))
        return bool(re.search(rf"\b{re.escape(keyword)}", query))


# Singleton instance
_router = AgentRouter()


def select_agent(query: str, session_state: Optional[Dict] = None) -> Dict:
    """Convenience function for single routing decision"""
    return _router.select_agent(query, session_state)
