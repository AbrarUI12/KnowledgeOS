import type { components } from "@knowledgeos/contracts";

import { apiClient } from "@/lib/api/client";
import { parseApiError } from "@/lib/api/errors";

export type Member = components["schemas"]["MemberOut"];
export type Group = components["schemas"]["GroupOut"];
export type Invitation = components["schemas"]["InvitationOut"];

/** Roles an admin can hand out; `owner` changes go through the API's last-owner rules. */
export const ROLES = ["owner", "admin", "knowledge_manager", "member", "viewer"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  knowledge_manager: "Knowledge manager",
  member: "Member",
  viewer: "Viewer",
};

type Client = ReturnType<typeof apiClient>;
export type AccessApi = { client: Client; organizationId: string };

export function createAccessApi(accessToken: string, organizationId: string): AccessApi {
  return { client: apiClient(accessToken, organizationId), organizationId };
}

// The client sends X-Organization-Id on every call; these routes also name the org in the path.
function scoped(organizationId: string) {
  return { path: { org_id: organizationId } };
}

function required<T>(data: T | undefined, response: Response, error: unknown): T {
  if (data === undefined) throw parseApiError(response.status, error);
  return data;
}

function succeeded(response: Response, error: unknown) {
  if (!response.ok) throw parseApiError(response.status, error);
}

export async function listMembers({ client, organizationId }: AccessApi): Promise<Member[]> {
  const { data, error, response } = await client.GET("/v1/organizations/{org_id}/members", {
    params: { ...scoped(organizationId), query: { limit: 200 } },
  });
  return required(data, response, error).items;
}

export async function updateMemberRole(
  { client, organizationId }: AccessApi,
  userId: string,
  role: Role,
): Promise<Member> {
  const { data, error, response } = await client.PATCH(
    "/v1/organizations/{org_id}/members/{user_id}",
    {
      params: {
        path: { org_id: organizationId, user_id: userId },
      },
      body: { role },
    },
  );
  return required(data, response, error);
}

export async function removeMember({ client, organizationId }: AccessApi, userId: string) {
  const { error, response } = await client.DELETE("/v1/organizations/{org_id}/members/{user_id}", {
    params: {
      path: { org_id: organizationId, user_id: userId },
    },
  });
  succeeded(response, error);
}

export async function inviteMember(
  { client, organizationId }: AccessApi,
  email: string,
  role: Role,
): Promise<Invitation> {
  const { data, error, response } = await client.POST("/v1/organizations/{org_id}/invitations", {
    params: scoped(organizationId),
    body: { email, role },
  });
  return required(data, response, error);
}

export async function listGroups({ client, organizationId }: AccessApi): Promise<Group[]> {
  const { data, error, response } = await client.GET("/v1/organizations/{org_id}/groups", {
    params: { ...scoped(organizationId), query: { limit: 200 } },
  });
  return required(data, response, error).items;
}

export async function createGroup(
  { client, organizationId }: AccessApi,
  name: string,
  description: string,
): Promise<Group> {
  const { data, error, response } = await client.POST("/v1/organizations/{org_id}/groups", {
    params: scoped(organizationId),
    body: { name, description: description || null },
  });
  return required(data, response, error);
}

export async function deleteGroup({ client, organizationId }: AccessApi, groupId: string) {
  const { error, response } = await client.DELETE("/v1/organizations/{org_id}/groups/{group_id}", {
    params: {
      path: { org_id: organizationId, group_id: groupId },
    },
  });
  succeeded(response, error);
}

export async function listGroupMembers(
  { client, organizationId }: AccessApi,
  groupId: string,
): Promise<Member[]> {
  const { data, error, response } = await client.GET(
    "/v1/organizations/{org_id}/groups/{group_id}/members",
    {
      params: {
        path: { org_id: organizationId, group_id: groupId },
        query: { limit: 200 },
      },
    },
  );
  return required(data, response, error).items;
}

export async function addGroupMember(
  { client, organizationId }: AccessApi,
  groupId: string,
  userId: string,
) {
  const { error, response } = await client.POST(
    "/v1/organizations/{org_id}/groups/{group_id}/members",
    {
      params: {
        path: { org_id: organizationId, group_id: groupId },
      },
      body: { user_id: userId },
    },
  );
  succeeded(response, error);
}

export async function removeGroupMember(
  { client, organizationId }: AccessApi,
  groupId: string,
  userId: string,
) {
  const { error, response } = await client.DELETE(
    "/v1/organizations/{org_id}/groups/{group_id}/members/{user_id}",
    {
      params: {
        path: { org_id: organizationId, group_id: groupId, user_id: userId },
      },
    },
  );
  succeeded(response, error);
}
