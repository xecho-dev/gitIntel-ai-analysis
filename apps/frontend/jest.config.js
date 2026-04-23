/** @type {import('jest').Config} */
module.exports = {
  rootDir: "./",
  roots: ["<rootDir>"],
  coverageDirectory: "coverage",
  coverageReporters: ["text", "json", "html"],
  coveragePathIgnorePatterns: [
    "/node_modules/",
    "/tests/setup.ts",
    ".*\\.config\\..*",
    "/\\.next/",
    "/dist/",
  ],
  setupFilesAfterEnv: ["<rootDir>/tests/setup.ts"],
  testEnvironment: "jest-environment-jsdom",
  testRegex: "tests/.+\\.test\\.(ts|tsx)$",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
  clearMocks: true,
  transform: {
    "^.+\\.(ts|tsx)$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
          esModuleInterop: true,
          allowSyntheticDefaultImports: true,
          module: "CommonJS",
          moduleResolution: "node",
        },
      },
    ],
  },
};
