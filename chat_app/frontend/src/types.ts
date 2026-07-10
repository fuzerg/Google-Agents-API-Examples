export interface Health {
  authenticated: boolean;
  project_id: string | null;
  location: string;
  error?: string | null;
}

export interface Config {
  default_project: string | null;
  location: string;
  default_model: string;
  recent_projects: string[];
  default_project_is_saved: boolean;
}

export interface AgentInfo {
  name: string | null; // resource path for agents, null for base models
  display_name: string;
  description: string | null;
  kind: "agent" | "model";
  model: string | null;
  project: string | null;
}

export interface AgentList {
  project: string;
  agents: AgentInfo[];
  error: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  agent: string | null;
  model: string;
  project: string | null;
  last_interaction_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  interaction_id: string | null;
  status: string;
  created_at: string;
}
