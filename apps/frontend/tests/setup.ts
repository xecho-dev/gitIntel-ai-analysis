import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
// NOTE: afterEach/describe/it/etc. are available globally via @types/jest.
// Ensure tsconfig includes "jest" in its "types" array (e.g. "types": ["jest", "@types/testing-library__jest-dom"]).

// Polyfill TextEncoder/TextDecoder for jsdom environment
if (typeof global.TextEncoder === "undefined") {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { TextEncoder: TE, TextDecoder: TD } = require("util");
  global.TextEncoder = TE;
  global.TextDecoder = TD;
}

afterEach(() => {
  cleanup();
});

// Mock next/navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Mock next-auth session
jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: {
      user: { id: "test-user-123", name: "Test User", email: "test@example.com" },
    },
    status: "authenticated",
  }),
  signIn: jest.fn(),
  signOut: jest.fn(),
}));

// Mock lucide-react icons to avoid render errors
jest.mock("lucide-react", () => ({
  BarChart3: () => null,
  Code2: () => null,
}));

// Suppress console.error for expected React warnings during tests
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    // Filter out known harmless React 18 warnings
    if (
      typeof args[0] === "string" &&
      (args[0].includes("Warning: An update to") ||
        args[0].includes("act(...)"))
    ) {
      return;
    }
    originalError.call(console, ...args);
  };
});

afterAll(() => {
  console.error = originalError;
});
