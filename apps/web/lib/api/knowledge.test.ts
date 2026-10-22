import { afterEach, describe, expect, it, vi } from "vitest";

import { uploadDocument, type KnowledgeApi, type UploadProgress } from "./knowledge";

const NativeXMLHttpRequest = globalThis.XMLHttpRequest;

afterEach(() => {
  globalThis.XMLHttpRequest = NativeXMLHttpRequest;
});

describe("uploadDocument", () => {
  it("reports XHR progress and sends only presigned headers to storage", async () => {
    const requestHeaders: Array<[string, string]> = [];
    const callbacks = new Map<string, (event: ProgressEvent) => void>();

    class XMLHttpRequestStub {
      status = 200;
      upload = {
        addEventListener: (name: string, callback: (event: ProgressEvent) => void) => {
          callbacks.set(`upload:${name}`, callback);
        },
      };
      open = vi.fn();
      setRequestHeader = (name: string, value: string) => requestHeaders.push([name, value]);
      addEventListener = (name: string, callback: (event: ProgressEvent) => void) => {
        callbacks.set(name, callback);
      };
      send = () => {
        callbacks.get("upload:progress")?.({
          lengthComputable: true,
          loaded: 5,
          total: 10,
        } as ProgressEvent);
        callbacks.get("load")?.({} as ProgressEvent);
      };
    }
    globalThis.XMLHttpRequest = XMLHttpRequestStub as unknown as typeof XMLHttpRequest;

    const post = vi
      .fn()
      .mockResolvedValueOnce({
        data: {
          upload_id: "upload-1",
          url: "https://storage.example/upload",
          method: "PUT",
          headers: { "Content-Type": "application/pdf" },
          expires_at: "2026-10-23T00:00:00Z",
        },
        response: new Response(null, { status: 201 }),
      })
      .mockResolvedValueOnce({
        data: {
          document_id: "document-1",
          document_version_id: "version-1",
          ingestion_job_id: "job-1",
          version_number: 1,
        },
        response: new Response(null, { status: 200 }),
      });
    const api = {
      client: { POST: post },
      organizationId: "org-1",
    } as unknown as KnowledgeApi;
    const progress: UploadProgress[] = [];

    const result = await uploadDocument(
      api,
      "kb-1",
      new File(["document"], "policy.pdf", { type: "application/pdf" }),
      "internal",
      (update) => progress.push(update),
    );

    expect(result.ingestion_job_id).toBe("job-1");
    expect(progress).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ state: "uploading", percent: 50 }),
        expect.objectContaining({ state: "done", percent: 100 }),
      ]),
    );
    expect(requestHeaders).toEqual([["Content-Type", "application/pdf"]]);
    expect(requestHeaders.flat().join(" ")).not.toContain("Authorization");
    expect(post).toHaveBeenNthCalledWith(
      2,
      "/v1/uploads/{upload_id}/complete",
      expect.objectContaining({
        params: expect.objectContaining({ header: { "X-Organization-Id": "org-1" } }),
      }),
    );
  });
});
