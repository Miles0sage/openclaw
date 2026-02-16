/**
 * Memory & Learning Module Exports
 * Public API for memory persistence system
 */

export { ClientMemoryService, getClientMemory, clearAllMemory } from "./client-memory.js";

export { ProjectMemoryService, getProjectMemory, clearAllProjectMemory } from "./project-memory.js";

export { SkillLoader, loadProjectSkills, loadProjectSkillsSync } from "./skill-loader.js";

export { MemoryIndexService, getMemoryIndex, resetMemoryIndex } from "./memory-index.js";

export type {
  Decision,
  ClientPreferences,
  ClientMemory,
  ProjectPattern,
  RecentChange,
  ProjectMemory,
  Skill,
  MemoryEntry,
  MemoryIndex,
  MemorySearchResult,
} from "./types.js";
