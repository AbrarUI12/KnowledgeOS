import createClient from "openapi-fetch";
import type { paths, components } from "../../../../packages/contracts/src/schema";

import { parseApiError } from "@/lib/api/errors";

export type Me = components["schemas"]["MeResponse"];
export type Membership = components["schemas"]["MembershipOut"];
export type Permission = components["schemas"]["Permission"];

export function apiClient(accessToken: string, organizationId?: string) {
  return createClient<paths>({
    baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(organizationId ? { "X-Organization-Id": organizationId } : {}),
    },
    credentials: "omit",
  });
}

export async function getMe(accessToken: string): Promise<Me> {
  const { data, error, response } = await apiClient(accessToken).GET("/v1/me");
  if (!data) throw parseApiError(response.status, error);
  return data;
}

export const queryKeys = {
  me: (userId: string) => ["me", userId] as const,
  organization: (userId: string, organizationId: string) =>
    ["organization", userId, organizationId] as const,
};
