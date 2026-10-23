"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/primitives/button";
import { Input } from "@/components/primitives/input";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/primitives/dialog";
import { useAccessApi, message } from "./members";
import {
  listGroups,
  createGroup,
  deleteGroup,
  listGroupMembers,
  listMembers,
  addGroupMember,
  removeGroupMember,
  type Group,
  type AccessApi,
} from "@/lib/api/access";

export function GroupsPage({
  organizationId,
  canManage,
}: {
  organizationId: string;
  canManage: boolean;
}) {
  const api = useAccessApi(organizationId);
  const cache = useQueryClient();
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Group | null>(null);
  const [removing, setRemoving] = useState<Group | null>(null);
  const key = ["groups", organizationId];
  const groups = useQuery({
    queryKey: key,
    queryFn: () => listGroups(api!),
    enabled: Boolean(api),
  });
  const create = useMutation({
    mutationFn: () => createGroup(api!, name.trim(), ""),
    onSuccess: async () => {
      setName("");
      await cache.invalidateQueries({ queryKey: key });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteGroup(api!, removing!.id),
    onSuccess: async () => {
      setRemoving(null);
      await cache.invalidateQueries({ queryKey: key });
    },
  });
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <h1 className="text-3xl font-semibold">Groups</h1>
      <p className="text-ink-secondary">Manage the people who share access through a group.</p>
      {canManage && (
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <Input
            aria-label="New group name"
            maxLength={200}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
            Create group
          </Button>
        </form>
      )}
      {create.error && <p role="alert">{message(create.error)}</p>}
      {groups.isPending ? (
        <p role="status">Loading groups…</p>
      ) : groups.error ? (
        <p role="alert">{message(groups.error)}</p>
      ) : (
        <ul className="divide-y divide-line rounded-panel border border-line bg-surface-0">
          {groups.data.map((group) => (
            <li key={group.id} className="flex items-center justify-between gap-3 p-4">
              <span className="font-medium">{group.name}</span>
              {canManage && (
                <div className="flex gap-2">
                  <Button onClick={() => setSelected(group)}>Manage members</Button>
                  <Button variant="danger" onClick={() => setRemoving(group)}>
                    Delete
                  </Button>
                </div>
              )}
            </li>
          ))}
          {groups.data.length === 0 && <li className="p-6 text-ink-secondary">No groups yet.</li>}
        </ul>
      )}
      {selected && api && (
        <GroupMembers api={api} group={selected} onClose={() => setSelected(null)} />
      )}
      <Dialog open={Boolean(removing)} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent>
          <DialogTitle>Delete {removing?.name}?</DialogTitle>
          <DialogDescription>Members lose access granted through this group.</DialogDescription>
          <Button onClick={() => setRemoving(null)}>Cancel</Button>
          {remove.error && <p role="alert">{message(remove.error)}</p>}
          <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
            Delete group
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
function GroupMembers({
  api,
  group,
  onClose,
}: {
  api: AccessApi;
  group: Group;
  onClose: () => void;
}) {
  const cache = useQueryClient();
  const [userId, setUserId] = useState("");
  const key = ["group-members", api.organizationId, group.id];
  const members = useQuery({ queryKey: key, queryFn: () => listGroupMembers(api, group.id) });
  const people = useQuery({
    queryKey: ["members", api.organizationId],
    queryFn: () => listMembers(api),
  });
  const change = useMutation({
    mutationFn: ({ id, add }: { id: string; add: boolean }) =>
      add ? addGroupMember(api, group.id, id) : removeGroupMember(api, group.id, id),
    onSuccess: async () => {
      setUserId("");
      await cache.invalidateQueries({ queryKey: key });
      await cache.invalidateQueries({ queryKey: ["members", api.organizationId] });
    },
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogTitle>{group.name}: members</DialogTitle>
        <DialogDescription>Add or remove organization members.</DialogDescription>
        <select
          aria-label="Person to add"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          className="rounded-control border border-control-border bg-surface-1 p-2"
        >
          <option value="">Choose a person</option>
          {people.data
            ?.filter((person) => !members.data?.some((member) => member.user_id === person.user_id))
            .map((person) => (
              <option key={person.user_id} value={person.user_id}>
                {person.display_name || person.email || person.user_id}
              </option>
            ))}
        </select>
        <Button
          disabled={!userId || change.isPending || members.isPending}
          onClick={() => change.mutate({ id: userId, add: true })}
        >
          Add member
        </Button>
        {members.isPending ? (
          <p role="status">Loading members…</p>
        ) : (
          <ul className="space-y-2">
            {members.data?.map((person) => (
              <li className="flex justify-between gap-2" key={person.user_id}>
                <span>{person.display_name || person.email || person.user_id}</span>
                <Button
                  disabled={change.isPending}
                  onClick={() => change.mutate({ id: person.user_id, add: false })}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
        {(members.error || people.error || change.error) && (
          <p role="alert">{message(members.error || people.error || change.error)}</p>
        )}
      </DialogContent>
    </Dialog>
  );
}
