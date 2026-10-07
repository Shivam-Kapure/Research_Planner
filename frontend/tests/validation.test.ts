import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { toResearchRequest, validateApiKey, validateCredentials, validateResearch } from "@/lib/validation";

const form = (overrides = {}) => ({
  question: "What is the effect of aerobic exercise on blood pressure?",
  maxIterations: 3,
  yearFrom: "",
  yearTo: "",
  ...overrides,
});

describe("research form", () => {
  test("accepts a reasonable question and sends only what the API expects", () => {
    assert.deepEqual(validateResearch(form()), {});
    assert.deepEqual(toResearchRequest(form({ question: "  Does sleep affect memory in adults?  ", yearFrom: "2015", maxIterations: 2 })), {
      question: "Does sleep affect memory in adults?",
      max_iterations: 2,
      year_from: 2015,
      year_to: null,
    });
  });

  test("mirrors the backend's limits", () => {
    assert.ok(validateResearch(form({ question: "too short" })).question);
    assert.ok(validateResearch(form({ question: "x".repeat(1001) })).question);
    assert.ok(validateResearch(form({ yearFrom: "15" })).yearFrom);
    assert.ok(validateResearch(form({ yearFrom: "1899" })).yearFrom);
    assert.ok(validateResearch(form({ yearFrom: "2020", yearTo: "2010" })).yearTo);
  });
});

describe("sign-in and registration", () => {
  test("requires a plausible email and, for registration, 10+ character passwords", () => {
    assert.deepEqual(validateCredentials("a@b.co", "anything", "login"), {});
    assert.ok(validateCredentials("not-an-email", "anything", "login").email);
    assert.ok(validateCredentials("a@b.co", "short", "register").password);
    assert.deepEqual(validateCredentials("a@b.co", "long enough!", "register"), {});
    assert.ok(validateCredentials("a@b.co", "", "login").password);
  });
});

describe("API key input", () => {
  test("rejects empty, short or whitespace-containing keys", () => {
    assert.ok(validateApiKey(""));
    assert.ok(validateApiKey("short"));
    assert.ok(validateApiKey("abcdefghij klmnopqrstuv"));
    assert.equal(validateApiKey("  abcdefghijklmnopqrstuvwxyz  "), null);
  });
});
