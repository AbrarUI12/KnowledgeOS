"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Copy, UserPlus, UserX } from "lucide-react";
import { useSession } from "next-auth/react";
import { useMemo, useState } from "react";

import { Button, IconButton } from "@/components/primitives/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/primitives/dialog";
import { Input } from "@/components/primitives/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/primitives/table";
import {
  ROLES,
  ROLE_LABELS,
  createAccessApi,
  inviteMember,
  listMembers,
  removeMember,
  updateMemberRole,
  type AccessApi,
  type Invitation,
  type Member,
  type Role,
} from "@/lib/api/access";

export function message(error: unknown) {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export function useAccessApi(organizationId: string): AccessApi | null {
  const { data: session } = useSession();
  return useMemo(
    () => (session?.accessToken ? createAccessApi(session.accessToken, organizationId) : null),
    [organizationId, session],
  );
}

export function roleLabel(role: string) {
  return ROLE_LABELS[role as Role] ?? role;
}

export function ErrorPanel({ title, error }: { title: string; error: unknown }) {
  return (
    <div role="alert" className="rounded-panel border border-danger bg-danger-soft p-4 text-danger">
      <p className="flex items-center gap-2 font-medium">
        <AlertCircle className="size-4" /> {title}
      </p>
      <p className="mt-1 text-sm">{message(error)}</p>
    </div>
  );
}

export function MembersPage({
  organizationId,
  currentUserId,
  canManage,
}: {
  organizationId: string;
  currentUserId: string;
  canManage: boolean;
}) {
  const api = useAccessApi(organizationId);
  const queryClient = useQueryClient();
  const key = ["members", organizationId];
  const members = useQuery({
    queryKey: key,
    queryFn: () => listMembers(api!),
    enabled: Boolean(api),
  });
  const [inviting, setInviting] = useState(false);
  const [removing, setRemoving] = useState<Member | null>(null);
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      updateMemberRole(api!, userId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember(api!, userId),
    onSuccess: async () => {
      setRemoving(null);
      await queryClient.invalidateQueries({ queryKey: key });
    },
  });

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-sm text-ink-secondary">Access</p>
          <h1 className="text-3xl font-semibold tracking-tight">Members</h1>
          <p className="mt-2 max-w-2xl text-ink-secondary">
            People in this organization and the role that decides what they can do.
          </p>
        </div>
        {canManage && (
          <Button variant="primary" onClick={() => setInviting(true)}>
            <UserPlus /> Invite
          </Button>
        )}
      </header>

      {members.isError ? (
        <ErrorPanel title="Members could not be loaded" error={members.error} />
      ) : members.isPending ? (
        <p role="status" className="text-ink-secondary">
          Loading members…
        </p>
      ) : (
        <div className="overflow-hidden rounded-panel border border-line bg-surface-0">
          <Table>
            <TableHeader className="bg-surface-2">
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Groups</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.data.map((member) => {
                const self = member.user_id === currentUserId;
                const name = member.display_name || member.email || member.user_id;
                return (
                  <TableRow key={member.user_id}>
                    <TableCell className="whitespace-normal">
                      <span className="block font-medium">
                        {name}
                        {self && <span className="ml-2 text-xs text-ink-secondary">(you)</span>}
                      </span>
                      {member.display_name && member.email && (
                        <span className="block text-xs text-ink-secondary">{member.email}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {canManage && !self ? (
                        <>
                          <label className="sr-only" htmlFor={`role-${member.user_id}`}>
                            Role of {name}
                          </label>
                          <select
                            id={`role-${member.user_id}`}
                            value={member.role}
                            disabled={changeRole.isPending}
                            onChange={(event) =>
                              changeRole.mutate({
                                userId: member.user_id,
                                role: event.target.value as Role,
                              })
                            }
                            className="h-control-md rounded-control border border-control-border bg-surface-1 px-2 text-sm"
                          >
                            {ROLES.map((role) => (
                              <option key={role} value={role}>
                                {ROLE_LABELS[role]}
                              </option>
                            ))}
                          </select>
                        </>
                      ) : (
                        roleLabel(member.role)
                      )}
                    </TableCell>
                    <TableCell className="tabular text-ink-secondary">
                      {member.group_ids?.length ?? 0}
                    </TableCell>
                    <TableCell className="text-right">
                      {canManage && !self && (
                        <IconButton
                          aria-label={`Remove ${name}`}
                          size="sm"
                          onClick={() => setRemoving(member)}
                        >
                          <UserX />
                        </IconButton>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      {changeRole.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {message(changeRole.error)}
        </p>
      )}

      {inviting && api && <InviteDialog api={api} onClose={() => setInviting(false)} />}
      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove member?</DialogTitle>
            <DialogDescription>
              {removing?.display_name || removing?.email} loses access to this organization
              immediately. Their past activity stays in the audit log.
            </DialogDescription>
          </DialogHeader>
          {remove.isError && (
            <p role="alert" className="text-sm text-danger">
              {message(remove.error)}
            </p>
          )}
          <DialogFooter>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => removing && remove.mutate(removing.user_id)}
            >
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function InviteDialog({ api, onClose }: { api: AccessApi; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [copied, setCopied] = useState(false);
  const invite = useMutation({ mutationFn: () => inviteMember(api, email.trim(), role) });
  const created: Invitation | undefined = invite.data;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>
            They join with this role after accepting the invitation link.
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="space-y-3">
            <p className="text-sm">
              Invitation for <strong>{created.email}</strong> ({roleLabel(created.role)}), valid
              until {new Date(created.expires_at).toLocaleString()}.
            </p>
            {created.accept_url && (
              <div className="flex items-center gap-2">
                <Input readOnly value={created.accept_url} aria-label="Invitation link" />
                <IconButton
                  aria-label="Copy invitation link"
                  onClick={async () => {
                    await navigator.clipboard.writeText(created.accept_url ?? "");
                    setCopied(true);
                  }}
                >
                  <Copy />
                </IconButton>
              </div>
            )}
            {copied && (
              <p role="status" className="text-sm text-success">
                Link copied.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label htmlFor="invite-email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="invite-email"
                type="email"
                autoFocus
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div>
              <label htmlFor="invite-role" className="text-sm font-medium">
                Role
              </label>
              <select
                id="invite-role"
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
                className="block h-control-md w-full rounded-control border border-control-border bg-surface-1 px-2 text-sm"
              >
                {ROLES.filter((item) => item !== "owner").map((item) => (
                  <option key={item} value={item}>
                    {ROLE_LABELS[item]}
                  </option>
                ))}
              </select>
            </div>
            {invite.isError && (
              <p role="alert" className="text-sm text-danger">
                {message(invite.error)}
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>{created ? "Done" : "Cancel"}</Button>
          {!created && (
            <Button
              variant="primary"
              disabled={!email.trim() || invite.isPending}
              onClick={() => invite.mutate()}
            >
              Create invitation
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
