"""
Agent Tool Profiles — per-agent tool allowlists for multi-agent delegation.

Each agent gets a filtered set of tools based on their role. When an agent
executes a step, only tools in its allowlist are available. This prevents
accidental misuse (e.g., the research agent deploying to Vercel).

If an agent has no profile entry, it gets unrestricted access (None).
"""

from typing import Optional, Set

# Per-agent tool allowlists.
# Keys match agent keys in config.json / AGENT_MAP.
# Values are sets of tool names from agent_tools.AGENT_TOOLS.
AGENT_TOOL_PROFILES: dict[str, set[str]] = {
    "project_manager": {
        "file_read", "glob_files", "grep_search",
        "web_search", "web_fetch", "web_scrape", "research_task",
        "github_repo_info", "github_create_issue",
        "create_job", "list_jobs", "approve_job",
        "create_proposal", "get_cost_summary", "get_events",
        "send_slack_message",
        "save_memory", "search_memory",
    },
    "coder_agent": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "install_package", "process_manage", "env_manage",
    },
    "elite_coder": {
        "shell_execute", "git_operations",
        "file_read", "file_write", "file_edit",
        "glob_files", "grep_search",
        "install_package", "process_manage", "env_manage",
        "vercel_deploy",
    },
    "hacker_agent": {
        "shell_execute",
        "file_read", "glob_files", "grep_search",
        "web_search", "web_fetch", "web_scrape",
        "github_repo_info",
    },
    "database_agent": {
        "shell_execute",
        "file_read", "file_write",
        "glob_files", "grep_search",
    },
    "research_agent": {
        "web_search", "web_fetch", "web_scrape", "research_task",
        "file_read", "glob_files", "grep_search",
        "save_memory", "search_memory",
        "github_repo_info",
    },
}


def get_tools_for_agent(agent_key: str) -> Optional[Set[str]]:
    """Return the tool allowlist for an agent, or None if unrestricted."""
    return AGENT_TOOL_PROFILES.get(agent_key)


def get_available_agents() -> list[str]:
    """Return all agent keys that have tool profiles defined."""
    return list(AGENT_TOOL_PROFILES.keys())
