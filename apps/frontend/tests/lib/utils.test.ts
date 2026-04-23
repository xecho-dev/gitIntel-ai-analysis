import { describe, it, expect } from "@jest/globals";
import { cn } from "@/lib/utils";

describe("cn — tailwind-merge utility", () => {
  it("merges class names", () => {
    const result = cn("px-2 py-2", "px-4");
    expect(result).toBe("py-2 px-4");
  });

  it("handles empty strings", () => {
    const result = cn("", "px-2", "");
    expect(result).toBe("px-2");
  });

  it("handles undefined and null", () => {
    const result = cn("px-2", undefined, null, "py-4");
    expect(result).toBe("px-2 py-4");
  });

  it("handles conditional classes", () => {
    const isActive = true;
    const isDisabled = false;
    const result = cn(
      "base-class",
      isActive && "active-class",
      isDisabled && "disabled-class"
    );
    expect(result).toContain("base-class");
    expect(result).toContain("active-class");
    expect(result).not.toContain("disabled-class");
  });

  it("handles array of class names", () => {
    const classes = ["px-2", "py-2"];
    const result = cn(...classes);
    expect(result).toBe("px-2 py-2");
  });

  it("handles object style classes", () => {
    const result = cn({
      "text-red-500": true,
      "text-blue-500": false,
    });
    expect(result).toBe("text-red-500");
  });
});
