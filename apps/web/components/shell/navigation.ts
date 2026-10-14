import type { Permission } from "@/lib/api/client";

export const navigation: { title: string; path: string; permission?: Permission }[] = [
  { title: "Home", path: "home" },
  { title: "Ask", path: "ask", permission: "query.execute" },
  { title: "Search", path: "search", permission: "query.execute" },
  { title: "Libraries", path: "knowledge/libraries", permission: "query.execute" },
  { title: "Documents", path: "knowledge/documents", permission: "query.execute" },
  { title: "Sources", path: "knowledge/sources", permission: "kb.manage" },
  { title: "Projects", path: "projects", permission: "query.execute" },
  { title: "Evaluate", path: "evaluate", permission: "evaluation.manage" },
  { title: "Observe", path: "observe", permission: "audit.read" },
  { title: "Members", path: "access/members", permission: "members.manage" },
  { title: "Groups", path: "access/groups", permission: "groups.manage" },
  { title: "Settings", path: "settings" },
];
