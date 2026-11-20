import { describe, expect, it } from "vitest";
import { findSkills, guessYears, type SkillVocab } from "./resume";

const vocab: SkillVocab = {
  skills: [
    { name: "SQL", pattern: "\\bsql\\b" },
    { name: "Snowflake", pattern: "\\bsnowflake\\b" },
    { name: "Data warehousing", pattern: "\\bdata warehous\\w*" },
    { name: "C#", pattern: "(?<![\\w#])c#(?![\\w#])|\\.net\\b" },
    { name: "Broken", pattern: "(" },
  ],
  implies: { Snowflake: ["Data warehousing"] },
};

describe("resume reading in the browser", () => {
  it("finds known skills, adds implied ones, and skips unreadable patterns", () => {
    expect(findSkills("Built SQL models on Snowflake; some C# too.", vocab)).toEqual([
      "C#",
      "Data warehousing",
      "Snowflake",
      "SQL",
    ]);
    expect(findSkills("Nothing relevant here", vocab)).toEqual([]);
  });

  it("guesses years of experience from the largest figure", () => {
    expect(guessYears("3 years at Acme, 5+ years overall")).toBe(5);
    expect(guessYears("120 years of company history")).toBeNull();
    expect(guessYears("no figures")).toBeNull();
  });
});
