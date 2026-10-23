"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  ChevronRight,
  FileText,
  FolderOpen,
  Plus,
  RefreshCw,
  ShieldAlert,
  Upload,
  X,
} from "lucide-react";
import { useSession } from "next-auth/react";
import { useMemo, useRef, useState } from "react";

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
import { StatusBadge } from "@/components/primitives/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/primitives/table";
import {
  createKnowledgeApi,
  createKnowledgeBase,
  decideDocumentVersion,
  inspectDocumentVersion,
  listDocumentVersions,
  listDocuments,
  listIngestionJobEvents,
  listIngestionJobs,
  listKnowledgeBases,
  retryIngestionJob,
  uploadDocument,
  type Classification,
  type Document,
  type IngestionJob,
  type KnowledgeApi,
  type UploadProgress,
} from "@/lib/api/knowledge";
import { ingestionLabel, ingestionStatus, isActiveIngestionState } from "@/lib/knowledge/status";

const ACCEPTED_FILES = ".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.html";

type Capabilities = {
  createLibrary: boolean;
  upload: boolean;
  publish: boolean;
};

function message(error: unknown) {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

function locationLabel(location: {
  page_start?: number | null;
  page_end?: number | null;
  slide_start?: number | null;
  slide_end?: number | null;
  sheet?: string | null;
  row_start?: number | null;
  row_end?: number | null;
}) {
  if (location.page_start)
    return `Page ${location.page_start}${location.page_end && location.page_end !== location.page_start ? `–${location.page_end}` : ""}`;
  if (location.slide_start)
    return `Slide ${location.slide_start}${location.slide_end && location.slide_end !== location.slide_start ? `–${location.slide_end}` : ""}`;
  if (location.sheet)
    return `${location.sheet}${location.row_start ? `, rows ${location.row_start}${location.row_end && location.row_end !== location.row_start ? `–${location.row_end}` : ""}` : ""}`;
  return "Source location unavailable";
}

export function KnowledgeLibrary({
  organizationId,
  capabilities,
}: {
  organizationId: string;
  capabilities: Capabilities;
}) {
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const client = useMemo(
    () => (session?.accessToken ? createKnowledgeApi(session.accessToken, organizationId) : null),
    [organizationId, session],
  );
  const [selectedLibraryId, setSelectedLibraryId] = useState<string | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [newLibraryName, setNewLibraryName] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [classification, setClassification] = useState<Classification>("internal");
  const [uploads, setUploads] = useState<(UploadProgress & { id: string })[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const libraries = useQuery({
    queryKey: ["knowledge-bases", organizationId],
    queryFn: () => listKnowledgeBases(client!),
    enabled: Boolean(client),
  });
  const selectedLibrary = libraries.data?.find((library) => library.id === selectedLibraryId);
  const effectiveLibraryId = selectedLibraryId ?? libraries.data?.[0]?.id ?? null;

  const documents = useQuery({
    queryKey: ["documents", organizationId, effectiveLibraryId],
    queryFn: () => listDocuments(client!, effectiveLibraryId!),
    enabled: Boolean(client && effectiveLibraryId),
    refetchInterval: (query) =>
      query.state.data?.items.some((document) => isActiveIngestionState(document.ingestion_state))
        ? 3_000
        : false,
  });
  const jobs = useQuery({
    queryKey: ["ingestion-jobs", organizationId, effectiveLibraryId],
    queryFn: () => listIngestionJobs(client!, effectiveLibraryId!),
    enabled: Boolean(client && effectiveLibraryId),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => isActiveIngestionState(job.state)) ? 3_000 : false,
  });
  const latestJobs = useMemo(() => {
    const byDocument = new Map<string, IngestionJob>();
    for (const job of jobs.data?.items ?? [])
      if (!byDocument.has(job.document_id)) byDocument.set(job.document_id, job);
    return byDocument;
  }, [jobs.data]);

  const createLibrary = useMutation({
    mutationFn: () => createKnowledgeBase(client!, newLibraryName.trim()),
    onSuccess: async (library) => {
      await queryClient.invalidateQueries({ queryKey: ["knowledge-bases", organizationId] });
      setSelectedLibraryId(library.id);
      setNewLibraryName("");
      setCreateOpen(false);
    },
  });
  const retry = useMutation({
    mutationFn: (jobId: string) => retryIngestionJob(client!, jobId),
    onSuccess: () => refreshLibrary(queryClient, organizationId, effectiveLibraryId),
  });

  async function handleFiles(files: FileList | null) {
    if (!client || !effectiveLibraryId || !files) return;
    for (const file of Array.from(files)) {
      const id = crypto.randomUUID();
      const update = (progress: UploadProgress) =>
        setUploads((current) => [...current.filter((item) => item.id !== id), { ...progress, id }]);
      try {
        await uploadDocument(client, effectiveLibraryId, file, classification, update);
      } catch (error) {
        update({ filename: file.name, percent: 0, state: "failed", error: message(error) });
      }
    }
    if (fileInput.current) fileInput.current.value = "";
    await refreshLibrary(queryClient, organizationId, effectiveLibraryId);
  }

  return (
    <div className="mx-auto max-w-7xl">
      <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 text-sm text-ink-secondary">Knowledge</p>
          <h1 className="text-3xl font-semibold tracking-tight">Library</h1>
          <p className="mt-2 max-w-2xl text-ink-secondary">
            Upload trusted source material and follow every document through ingestion.
          </p>
        </div>
        {capabilities.createLibrary && (
          <Button variant="secondary" onClick={() => setCreateOpen(true)}>
            <Plus /> New library
          </Button>
        )}
      </header>

      {libraries.isError ? (
        <ErrorPanel title="Libraries could not be loaded" error={libraries.error} />
      ) : libraries.isPending ? (
        <p role="status" className="text-ink-secondary">
          Loading libraries…
        </p>
      ) : libraries.data.length === 0 ? (
        <EmptyLibrary canCreate={capabilities.createLibrary} onCreate={() => setCreateOpen(true)} />
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside
            className="rounded-panel border border-line bg-surface-0 p-2"
            aria-label="Libraries"
          >
            <ul className="space-y-1">
              {libraries.data.map((library) => {
                const active = library.id === effectiveLibraryId;
                return (
                  <li key={library.id}>
                    <button
                      className="flex w-full items-center gap-3 rounded-control px-3 py-3 text-left hover:bg-surface-2 aria-pressed:bg-accent-soft"
                      aria-pressed={active}
                      onClick={() => {
                        setSelectedLibraryId(library.id);
                        setSelectedDocument(null);
                      }}
                    >
                      <FolderOpen className={active ? "text-accent" : "text-ink-tertiary"} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{library.name}</span>
                        <span className="block text-xs text-ink-secondary">
                          {library.document_count}{" "}
                          {library.document_count === 1 ? "document" : "documents"}
                        </span>
                      </span>
                      <ChevronRight className="size-4 text-ink-tertiary" aria-hidden />
                    </button>
                  </li>
                );
              })}
            </ul>
          </aside>

          <section aria-labelledby="selected-library-heading" className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 id="selected-library-heading" className="text-xl font-semibold">
                  {
                    (
                      selectedLibrary ??
                      libraries.data.find((item) => item.id === effectiveLibraryId)
                    )?.name
                  }
                </h2>
                <p className="text-sm text-ink-secondary">
                  {(
                    selectedLibrary ?? libraries.data.find((item) => item.id === effectiveLibraryId)
                  )?.visibility === "restricted"
                    ? "Restricted access"
                    : "Organization access"}
                </p>
              </div>
              {capabilities.upload && (
                <div className="flex items-center gap-2">
                  <label className="sr-only" htmlFor="upload-classification">
                    Classification
                  </label>
                  <select
                    id="upload-classification"
                    value={classification}
                    onChange={(event) => setClassification(event.target.value as Classification)}
                    className="h-control-md rounded-control border border-control-border bg-surface-1 px-2 text-sm"
                  >
                    <option value="public">Public</option>
                    <option value="internal">Internal</option>
                    <option value="confidential">Confidential</option>
                    <option value="restricted">Restricted</option>
                  </select>
                  <input
                    ref={fileInput}
                    className="sr-only"
                    type="file"
                    multiple
                    accept={ACCEPTED_FILES}
                    onChange={(event) => void handleFiles(event.target.files)}
                  />
                  <Button variant="primary" onClick={() => fileInput.current?.click()}>
                    <Upload /> Upload
                  </Button>
                </div>
              )}
            </div>

            {uploads.length > 0 && <UploadQueue uploads={uploads} dismiss={() => setUploads([])} />}

            {documents.isError || jobs.isError ? (
              <ErrorPanel
                title="Documents could not be loaded"
                error={documents.error ?? jobs.error}
              />
            ) : documents.isPending ? (
              <p
                role="status"
                className="rounded-panel border border-line bg-surface-0 p-5 text-ink-secondary"
              >
                Loading documents…
              </p>
            ) : documents.data.items.length === 0 ? (
              <div className="rounded-panel border border-dashed border-line-strong bg-surface-0 p-10 text-center">
                <FileText className="mx-auto mb-3 text-ink-tertiary" aria-hidden />
                <h3 className="font-semibold">No documents yet</h3>
                <p className="mt-1 text-sm text-ink-secondary">
                  {capabilities.upload
                    ? "Upload a file to begin ingestion."
                    : "A knowledge manager can add the first source."}
                </p>
              </div>
            ) : (
              <DocumentTable
                documents={documents.data.items}
                jobs={latestJobs}
                canRetry={capabilities.upload}
                retrying={retry.isPending}
                onRetry={(jobId) => retry.mutate(jobId)}
                onInspect={setSelectedDocument}
              />
            )}
            {retry.isError && (
              <p role="alert" className="mt-3 text-sm text-danger">
                {message(retry.error)}
              </p>
            )}
          </section>
        </div>
      )}

      <CreateLibraryDialog
        open={createOpen}
        name={newLibraryName}
        pending={createLibrary.isPending}
        error={createLibrary.error}
        setName={setNewLibraryName}
        setOpen={setCreateOpen}
        submit={() => createLibrary.mutate()}
      />
      {selectedDocument && client && (
        <InspectDialog
          client={client}
          organizationId={organizationId}
          document={selectedDocument}
          job={latestJobs.get(selectedDocument.id)}
          canPublish={capabilities.publish}
          onClose={() => setSelectedDocument(null)}
          onChanged={() => refreshLibrary(queryClient, organizationId, effectiveLibraryId)}
        />
      )}
    </div>
  );
}

function refreshLibrary(
  queryClient: ReturnType<typeof useQueryClient>,
  organizationId: string,
  knowledgeBaseId: string | null,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["knowledge-bases", organizationId] }),
    queryClient.invalidateQueries({ queryKey: ["documents", organizationId, knowledgeBaseId] }),
    queryClient.invalidateQueries({
      queryKey: ["ingestion-jobs", organizationId, knowledgeBaseId],
    }),
  ]);
}

function DocumentTable({
  documents,
  jobs,
  canRetry,
  retrying,
  onRetry,
  onInspect,
}: {
  documents: Document[];
  jobs: Map<string, IngestionJob>;
  canRetry: boolean;
  retrying: boolean;
  onRetry: (jobId: string) => void;
  onInspect: (document: Document) => void;
}) {
  return (
    <div className="overflow-hidden rounded-panel border border-line bg-surface-0">
      <Table>
        <TableHeader className="bg-surface-2">
          <TableRow>
            <TableHead>Document</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Classification</TableHead>
            <TableHead>Updated</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents.map((document) => {
            const job = jobs.get(document.id);
            const state = job?.state ?? document.ingestion_state;
            return (
              <TableRow key={document.id}>
                <TableCell className="max-w-80 whitespace-normal">
                  <button
                    className="text-left font-medium text-accent hover:underline"
                    onClick={() => onInspect(document)}
                  >
                    {document.title}
                  </button>
                  <span className="mt-1 block text-xs text-ink-secondary">
                    Version {document.latest_version_number}
                    {document.document_type ? ` · ${document.document_type}` : ""}
                  </span>
                  {job?.error_detail_safe && (
                    <span className="mt-1 block text-xs text-danger">{job.error_detail_safe}</span>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge status={ingestionStatus(state)}>{ingestionLabel(state)}</StatusBadge>
                  {job && isActiveIngestionState(job.state) && (
                    <span className="ml-2 tabular text-xs text-ink-secondary">
                      {job.progress_percent}%
                    </span>
                  )}
                </TableCell>
                <TableCell className="capitalize">{document.classification}</TableCell>
                <TableCell className="text-ink-secondary">
                  {formatDate(document.updated_at ?? document.created_at)}
                </TableCell>
                <TableCell className="text-right">
                  {job?.retryable && canRetry ? (
                    <Button size="sm" disabled={retrying} onClick={() => onRetry(job.id)}>
                      <RefreshCw /> Retry
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => onInspect(document)}>
                      Inspect
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function UploadQueue({
  uploads,
  dismiss,
}: {
  uploads: (UploadProgress & { id: string })[];
  dismiss: () => void;
}) {
  return (
    <section
      aria-label="Uploads"
      className="mb-4 rounded-panel border border-line bg-surface-0 p-4"
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-medium">Uploads</h3>
        <IconButton aria-label="Dismiss completed uploads" size="sm" onClick={dismiss}>
          <X />
        </IconButton>
      </div>
      <ul className="space-y-3">
        {uploads.map((upload) => (
          <li key={upload.id}>
            <div className="mb-1 flex justify-between gap-3 text-sm">
              <span className="truncate">{upload.filename}</span>
              <span className={upload.state === "failed" ? "text-danger" : "text-ink-secondary"}>
                {upload.state === "done"
                  ? "Queued"
                  : upload.state === "failed"
                    ? "Failed"
                    : `${upload.percent}%`}
              </span>
            </div>
            <div
              className="h-1.5 overflow-hidden rounded-full bg-surface-2"
              role="progressbar"
              aria-label={`${upload.filename} upload progress`}
              aria-valuenow={upload.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`h-full ${upload.state === "failed" ? "bg-danger" : "bg-accent"}`}
                style={{ width: `${upload.percent}%` }}
              />
            </div>
            {upload.error && (
              <p role="alert" className="mt-1 text-xs text-danger">
                {upload.error}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function InspectDialog({
  client,
  organizationId,
  document,
  job,
  canPublish,
  onClose,
  onChanged,
}: {
  client: KnowledgeApi;
  organizationId: string;
  document: Document;
  job?: IngestionJob;
  canPublish: boolean;
  onClose: () => void;
  onChanged: () => Promise<unknown>;
}) {
  const queryClient = useQueryClient();
  const versions = useQuery({
    queryKey: ["document-versions", organizationId, document.id],
    queryFn: () => listDocumentVersions(client, document.id),
  });
  const latestVersion = versions.data?.[0];
  const inspection = useQuery({
    queryKey: ["document-inspection", organizationId, document.id, latestVersion?.id],
    queryFn: () => inspectDocumentVersion(client, document.id, latestVersion!.id),
    enabled: Boolean(latestVersion),
  });
  const events = useQuery({
    queryKey: ["ingestion-events", organizationId, job?.id],
    queryFn: () => listIngestionJobEvents(client, job!.id),
    enabled: Boolean(job),
    refetchInterval: job && isActiveIngestionState(job.state) ? 3_000 : false,
  });
  const decision = useMutation({
    mutationFn: (choice: "approve" | "reject") =>
      decideDocumentVersion(client, document.id, latestVersion!.id, choice),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["document-versions", organizationId, document.id],
      });
      await onChanged();
    },
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{document.title}</DialogTitle>
          <DialogDescription>
            Version {document.latest_version_number} · {document.classification} ·{" "}
            {ingestionLabel(job?.state ?? document.ingestion_state)}
          </DialogDescription>
        </DialogHeader>
        {versions.isPending || (latestVersion && inspection.isPending) ? (
          <p role="status" className="py-8 text-center text-ink-secondary">
            Loading inspection…
          </p>
        ) : versions.isError || inspection.isError ? (
          <ErrorPanel
            title="Inspection is unavailable"
            error={versions.error ?? inspection.error}
          />
        ) : inspection.data ? (
          <div className="space-y-6">
            {inspection.data.canonical && (
              <div className="grid gap-3 rounded-control bg-surface-2 p-4 text-sm sm:grid-cols-3">
                <div>
                  <span className="block text-xs text-ink-secondary">Parser</span>
                  {inspection.data.canonical.parser_name} {inspection.data.canonical.parser_version}
                </div>
                <div>
                  <span className="block text-xs text-ink-secondary">Pages</span>
                  {inspection.data.canonical.page_count ?? "—"}
                </div>
                <div>
                  <span className="block text-xs text-ink-secondary">Languages</span>
                  {inspection.data.canonical.languages?.join(", ") || "—"}
                </div>
              </div>
            )}
            <section aria-labelledby="findings-heading">
              <h3 id="findings-heading" className="mb-3 flex items-center gap-2 font-semibold">
                <ShieldAlert className="size-4" /> Scan findings
              </h3>
              {(inspection.data.content_findings?.length ?? 0) === 0 ? (
                <p className="flex items-center gap-2 text-sm text-success">
                  <Check className="size-4" /> No content-security findings.
                </p>
              ) : (
                <ul className="space-y-2">
                  {inspection.data.content_findings?.map((finding, index) => (
                    <li
                      key={`${finding.rule_id}-${index}`}
                      className="rounded-control border border-warning bg-warning-soft p-3 text-sm"
                    >
                      <strong>{finding.rule_id}</strong> · severity {finding.severity}
                      {finding.detail && (
                        <span className="block text-ink-secondary">{finding.detail}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="chunks-heading">
              <h3 id="chunks-heading" className="mb-3 font-semibold">
                Chunks ({inspection.data.chunks.length})
              </h3>
              {inspection.data.chunks.length === 0 ? (
                <p className="text-sm text-ink-secondary">Chunks are not available yet.</p>
              ) : (
                <ol className="max-h-64 space-y-2 overflow-y-auto pr-1">
                  {inspection.data.chunks.map((chunk) => (
                    <li key={chunk.id} className="rounded-control border border-line p-3 text-sm">
                      <span className="font-medium">Chunk {chunk.ordinal + 1}</span>
                      <span className="ml-2 text-ink-secondary">
                        {chunk.token_count} tokens · {locationLabel(chunk.location)}
                      </span>
                      {chunk.section_path.length > 0 && (
                        <span className="mt-1 block text-xs text-ink-secondary">
                          {chunk.section_path.join(" / ")}
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
            <section aria-labelledby="timeline-heading">
              <h3 id="timeline-heading" className="mb-3 font-semibold">
                Timeline
              </h3>
              {events.isError ? (
                <p className="text-sm text-danger">{message(events.error)}</p>
              ) : (
                <ol className="border-l border-line pl-4">
                  {events.data?.map((event, index) => (
                    <li key={`${event.at}-${index}`} className="mb-3 text-sm">
                      <p className="font-medium">{ingestionLabel(event.state)}</p>
                      <p className="text-xs text-ink-secondary">
                        {formatDate(event.at)}
                        {event.message ? ` · ${event.message}` : ""}
                      </p>
                    </li>
                  ))}
                  {!events.isPending && events.data?.length === 0 && (
                    <li className="text-sm text-ink-secondary">No events recorded.</li>
                  )}
                </ol>
              )}
            </section>
          </div>
        ) : (
          <p className="py-8 text-center text-ink-secondary">No version is available to inspect.</p>
        )}
        {decision.isError && (
          <p role="alert" className="text-sm text-danger">
            {message(decision.error)}
          </p>
        )}
        <DialogFooter>
          {canPublish && latestVersion?.approval_status === "pending" && (
            <>
              <Button
                variant="danger"
                disabled={decision.isPending}
                onClick={() => decision.mutate("reject")}
              >
                <X /> Reject
              </Button>
              <Button
                variant="primary"
                disabled={decision.isPending}
                onClick={() => decision.mutate("approve")}
              >
                <Check /> Approve
              </Button>
            </>
          )}
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreateLibraryDialog({
  open,
  name,
  pending,
  error,
  setName,
  setOpen,
  submit,
}: {
  open: boolean;
  name: string;
  pending: boolean;
  error: unknown;
  setName: (name: string) => void;
  setOpen: (open: boolean) => void;
  submit: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create a library</DialogTitle>
          <DialogDescription>
            Start an organization-visible collection of related sources.
          </DialogDescription>
        </DialogHeader>
        <label htmlFor="library-name" className="text-sm font-medium">
          Name
        </label>
        <Input
          id="library-name"
          autoFocus
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && name.trim()) submit();
          }}
        />
        {error != null && (
          <p role="alert" className="text-sm text-danger">
            {message(error)}
          </p>
        )}
        <DialogFooter>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" disabled={!name.trim() || pending} onClick={submit}>
            Create library
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EmptyLibrary({ canCreate, onCreate }: { canCreate: boolean; onCreate: () => void }) {
  return (
    <div className="rounded-panel border border-dashed border-line-strong bg-surface-0 p-12 text-center">
      <FolderOpen className="mx-auto mb-4 text-ink-tertiary" aria-hidden />
      <h2 className="text-lg font-semibold">Create your first knowledge library</h2>
      <p className="mx-auto mt-2 max-w-md text-ink-secondary">
        Libraries keep documents, access, and retrieval scope together.
      </p>
      {canCreate && (
        <Button className="mt-5" variant="primary" onClick={onCreate}>
          <Plus /> New library
        </Button>
      )}
    </div>
  );
}

function ErrorPanel({ title, error }: { title: string; error: unknown }) {
  return (
    <div role="alert" className="rounded-panel border border-danger bg-danger-soft p-4 text-danger">
      <p className="flex items-center gap-2 font-medium">
        <AlertCircle className="size-4" /> {title}
      </p>
      <p className="mt-1 text-sm">{message(error)}</p>
    </div>
  );
}
