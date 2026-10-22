import type { components } from "@knowledgeos/contracts";

import { apiClient } from "@/lib/api/client";
import { ApiError, parseApiError } from "@/lib/api/errors";

export type KnowledgeBase = components["schemas"]["KnowledgeBaseOut"];
export type Document = components["schemas"]["DocumentOut"];
export type DocumentVersion = components["schemas"]["DocumentVersionOut"];
export type DocumentInspection = components["schemas"]["DocumentInspection"];
export type IngestionJob = components["schemas"]["IngestionJobOut"];
export type IngestionJobEvent = components["schemas"]["IngestionJobEvent"];
export type IngestionState = components["schemas"]["IngestionState"];
export type Classification = components["schemas"]["Classification"];

type Client = ReturnType<typeof apiClient>;
export type KnowledgeApi = { client: Client; organizationId: string };

export function createKnowledgeApi(accessToken: string, organizationId: string): KnowledgeApi {
  return { client: apiClient(accessToken, organizationId), organizationId };
}

function header(organizationId: string) {
  return { "X-Organization-Id": organizationId };
}

function required<T>(data: T | undefined, response: Response, error: unknown): T {
  if (data === undefined) throw parseApiError(response.status, error);
  return data;
}

export async function listKnowledgeBases({
  client,
  organizationId,
}: KnowledgeApi): Promise<KnowledgeBase[]> {
  const { data, error, response } = await client.GET("/v1/knowledge-bases", {
    params: { header: header(organizationId) },
  });
  return required(data, response, error);
}

export async function createKnowledgeBase(
  { client, organizationId }: KnowledgeApi,
  name: string,
): Promise<KnowledgeBase> {
  const { data, error, response } = await client.POST("/v1/knowledge-bases", {
    params: { header: header(organizationId) },
    body: { name, visibility: "organization" },
  });
  return required(data, response, error);
}

export async function listDocuments(
  { client, organizationId }: KnowledgeApi,
  knowledgeBaseId: string,
) {
  const { data, error, response } = await client.GET("/v1/knowledge-bases/{kb_id}/documents", {
    params: {
      path: { kb_id: knowledgeBaseId },
      query: { limit: 200, sort: "-updated_at" },
      header: header(organizationId),
    },
  });
  return required(data, response, error);
}

export async function listIngestionJobs(
  { client, organizationId }: KnowledgeApi,
  knowledgeBaseId: string,
) {
  const { data, error, response } = await client.GET("/v1/knowledge-bases/{kb_id}/ingestion-jobs", {
    params: {
      path: { kb_id: knowledgeBaseId },
      query: { limit: 200 },
      header: header(organizationId),
    },
  });
  return required(data, response, error);
}

export async function listDocumentVersions(
  { client, organizationId }: KnowledgeApi,
  documentId: string,
) {
  const { data, error, response } = await client.GET("/v1/documents/{document_id}/versions", {
    params: { path: { document_id: documentId }, header: header(organizationId) },
  });
  return required(data, response, error);
}

export async function inspectDocumentVersion(
  api: KnowledgeApi,
  documentId: string,
  versionId: string,
): Promise<DocumentInspection> {
  const { client, organizationId } = api;
  const { data, error, response } = await client.GET(
    "/v1/documents/{document_id}/versions/{version_id}/inspect",
    {
      params: {
        path: { document_id: documentId, version_id: versionId },
        header: header(organizationId),
      },
    },
  );
  return required(data, response, error);
}

export async function listIngestionJobEvents(
  { client, organizationId }: KnowledgeApi,
  jobId: string,
) {
  const { data, error, response } = await client.GET("/v1/ingestion-jobs/{job_id}/events", {
    params: { path: { job_id: jobId }, header: header(organizationId) },
  });
  return required(data, response, error);
}

export async function retryIngestionJob({ client, organizationId }: KnowledgeApi, jobId: string) {
  const { data, error, response } = await client.POST("/v1/ingestion-jobs/{job_id}/retry", {
    params: { path: { job_id: jobId }, header: header(organizationId) },
  });
  return required(data, response, error);
}

export async function decideDocumentVersion(
  api: KnowledgeApi,
  documentId: string,
  versionId: string,
  decision: "approve" | "reject",
) {
  const { client, organizationId } = api;
  const request =
    decision === "approve"
      ? client.POST("/v1/documents/{document_id}/versions/{version_id}/approve", {
          params: {
            path: { document_id: documentId, version_id: versionId },
            header: header(organizationId),
          },
          body: {},
        })
      : client.POST("/v1/documents/{document_id}/versions/{version_id}/reject", {
          params: {
            path: { document_id: documentId, version_id: versionId },
            header: header(organizationId),
          },
          body: {},
        });
  const { data, error, response } = await request;
  return required(data, response, error);
}

export type UploadProgress = {
  filename: string;
  percent: number;
  state: "preparing" | "uploading" | "completing" | "done" | "failed";
  error?: string;
};

function putPresigned(
  file: File,
  url: string,
  headers: Record<string, string>,
  onProgress: (percent: number) => void,
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    for (const [name, value] of Object.entries(headers)) request.setRequestHeader(name, value);
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new ApiError(request.status, "upload_failed", "The file upload failed."));
    });
    request.addEventListener("error", () =>
      reject(new ApiError(0, "upload_failed", "The storage service could not be reached.")),
    );
    request.addEventListener("abort", () =>
      reject(new ApiError(0, "upload_cancelled", "The file upload was cancelled.")),
    );
    request.send(file);
  });
}

export async function uploadDocument(
  api: KnowledgeApi,
  knowledgeBaseId: string,
  file: File,
  classification: Classification,
  onProgress: (progress: UploadProgress) => void,
) {
  const { client, organizationId } = api;
  onProgress({ filename: file.name, percent: 0, state: "preparing" });
  const created = await client.POST("/v1/knowledge-bases/{kb_id}/uploads", {
    params: { path: { kb_id: knowledgeBaseId }, header: header(organizationId) },
    body: {
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
    },
  });
  const upload = required(created.data, created.response, created.error);
  onProgress({ filename: file.name, percent: 0, state: "uploading" });
  await putPresigned(file, upload.url, upload.headers ?? {}, (percent) =>
    onProgress({ filename: file.name, percent, state: "uploading" }),
  );
  onProgress({ filename: file.name, percent: 100, state: "completing" });
  const completed = await client.POST("/v1/uploads/{upload_id}/complete", {
    params: { path: { upload_id: upload.upload_id }, header: header(organizationId) },
    body: { title: file.name, classification },
  });
  const result = required(completed.data, completed.response, completed.error);
  onProgress({ filename: file.name, percent: 100, state: "done" });
  return result;
}
