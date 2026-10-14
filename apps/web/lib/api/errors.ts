import { z } from "zod";

const errorEnvelope = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().nullable().optional(),
    details: z.record(z.string(), z.unknown()).nullable().optional(),
  }),
});

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function parseApiError(status: number, body: unknown): ApiError {
  const result = errorEnvelope.safeParse(body);
  if (!result.success)
    return new ApiError(status, "unexpected_response", "The request could not be completed.");
  const error = result.data.error;
  return new ApiError(status, error.code, error.message, error.request_id);
}
