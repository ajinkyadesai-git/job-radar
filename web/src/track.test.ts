import { describe, expect, it } from "vitest";
import { referrerHost } from "./track";

describe("referrerHost", () => {
  it("prefers the ref passed by the GitHub Pages link", () => {
    expect(referrerHost("?ref=linkedin.com", "https://ajinkyadesai-git.github.io/", "x.net")).toBe(
      "linkedin.com",
    );
  });
  it("keeps only the host of the browser's referrer", () => {
    expect(referrerHost("", "https://www.linkedin.com/feed/?id=9", "x.net")).toBe("www.linkedin.com");
  });
  it("ignores our own pages and empty referrers", () => {
    expect(referrerHost("", "https://x.net/#ask", "x.net")).toBe("");
    expect(referrerHost("", "", "x.net")).toBe("");
  });
});
