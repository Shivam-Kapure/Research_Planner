import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { ApiClient, ApiError, errorMessage } from "@/lib/api/client";
import { createApi } from "@/lib/api/endpoints";

type Seen = { url: string; init: RequestInit };

function respond(status: number, body?: unknown, contentType = "application/json") {
  const seen: Seen[] = [];
  const fetch = (async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    const text = body === undefined ? null : typeof body === "string" ? body : JSON.stringify(body);
    return new Response(text, { status, headers: text === null ? {} : { "content-type": contentType } });
  }) as unknown as typeof globalThis.fetch;
  return { fetch, seen };
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof ApiError);
    return error;
  }
  assert.fail("expected the request to fail");
}

describe("ApiClient", () => {
  test("calls the same-origin /api proxy with JSON and the session cookie", async () => {
    const { fetch, seen } = respond(202, { id: "r1", status: "queued" });
    const api = createApi(new ApiClient({ fetch }));
    const run = await api.createRun({ question: "A question of at least fifteen characters" });
    assert.equal(run.id, "r1");
    assert.equal(seen[0].url, "/api/runs");
    assert.equal(seen[0].init.method, "POST");
    assert.equal(seen[0].init.credentials, "same-origin");
    assert.deepEqual(JSON.parse(String(seen[0].init.body)), { question: "A question of at least fifteen characters" });
  });

  test("builds the events cursor URL", async () => {
    const { fetch, seen } = respond(200, []);
    await createApi(new ApiClient({ fetch })).events("abc", 42);
    assert.equal(seen[0].url, "/api/runs/abc/events?after=42&limit=200");
  });

  test("turns FastAPI 422 details into field errors", async () => {
    const { fetch } = respond(422, {
      detail: [
        { loc: ["body", "question"], msg: "String should have at least 15 characters", type: "string_too_short" },
        { loc: ["body"], msg: "Value error, year_from must not be after year_to", type: "value_error" },
      ],
    });
    const error = await failure(new ApiClient({ fetch }).request("POST", "/runs", {}));
    assert.equal(error.kind, "validation");
    assert.deepEqual(error.fieldErrors, [
      { field: "question", message: "String should have at least 15 characters" },
      { field: "", message: "year_from must not be after year_to" },
    ]);
    assert.match(errorMessage(error), /question: String should have at least 15/);
  });

  test("reports a 401 to the session layer", async () => {
    const { fetch } = respond(401, { detail: "Not authenticated" });
    let notified = 0;
    const client = new ApiClient({ fetch, onUnauthorized: () => notified++ });
    const error = await failure(client.request("GET", "/auth/me"));
    assert.equal(error.kind, "unauthorized");
    assert.equal(notified, 1);
  });

  test("classifies statuses the UI treats differently", async () => {
    const cases: [number, unknown, string, string][] = [
      [404, { detail: "Run not found" }, "application/json", "not_found"],
      [409, { detail: "A run is already in progress" }, "application/json", "conflict"],
      [429, { detail: "slow down" }, "application/json", "rate_limited"],
      [500, { detail: "boom" }, "application/json", "server"],
      [500, "Internal Server Error", "text/plain", "unavailable"], // the dev proxy cannot connect
      [503, { status: "not_ready" }, "application/json", "unavailable"],
      [502, "Bad Gateway", "text/html", "unavailable"],
    ];
    for (const [status, body, type, kind] of cases) {
      const { fetch } = respond(status, body, type);
      const error = await failure(new ApiClient({ fetch }).request("GET", "/runs"));
      assert.equal(error.kind, kind, `HTTP ${status}`);
    }
  });

  test("a network failure is transient and carries no internals", async () => {
    const fetch = (async () => {
      throw new TypeError("fetch failed: ECONNREFUSED 10.0.0.5:8000");
    }) as unknown as typeof globalThis.fetch;
    const error = await failure(new ApiClient({ fetch }).request("GET", "/runs"));
    assert.equal(error.kind, "unavailable");
    assert.ok(error.transient);
    assert.doesNotMatch(error.message, /ECONNREFUSED|10\.0\.0\.5/);
  });

  test("204 responses resolve without a body", async () => {
    const { fetch } = respond(204);
    assert.equal(await createApi(new ApiClient({ fetch })).deleteCredential("groq"), undefined);
  });
});
