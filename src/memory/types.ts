/**
 * Memory & Learning Module Types
 * Defines interfaces for persistent client/project knowledge storage
 */

export interface Decision {
  date: string;
  decision: string;
  reason: string;
  outcome?: string;
}

export interface ClientPreferences {
  techStack?: string;
  styling?: string;
  codingStandards?: string;
  brandColors?: {
    primary?: string;
    secondary?: string;
  };
  [key: string]: unknown;
}

export interface ClientMemory {
  clientId: string;
  preferences: ClientPreferences;
  pastDecisions: Decision[];
  skillsToUse: string[];
  lastUpdated: number;
}

export interface ProjectPattern {
  name: string;
  description?: string;
  example?: string;
}

export interface RecentChange {
  date: string;
  change: string;
  file: string;
}

export interface ProjectMemory {
  projectId: string;
  architecture?: string;
  keyFiles: {
    components?: string[];
    api?: string[];
    database?: string[];
    config?: string[];
    [key: string]: string[] | undefined;
  };
  patterns: ProjectPattern[];
  dependencies: Record<string, string>;
  recentChanges: RecentChange[];
  lastModified: number;
}

export interface Skill {
  title: string;
  tags: string[];
  version?: string;
  appliesTo?: string[];
  content: string;
  filePath?: string;
}

export interface MemoryEntry {
  clientId: string;
  projectId?: string;
  clientMemory?: ClientMemory;
  projectMemory?: ProjectMemory;
  skills?: Skill[];
  timestamp: number;
}

export interface MemoryIndex {
  clients: Map<string, ClientMemory>;
  projects: Map<string, ProjectMemory>;
  skills: Skill[];
  lastIndexed: number;
}

export interface MemorySearchResult {
  type: "client" | "project" | "skill";
  id: string;
  title?: string;
  match?: string;
  relevance: number;
}
