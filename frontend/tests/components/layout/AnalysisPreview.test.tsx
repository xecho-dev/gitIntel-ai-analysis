import { describe, it, expect, beforeEach } from "@jest/globals";
import { render, screen } from "@testing-library/react";
import { AnalysisPreview } from "@/components/layout/AnalysisPreview";
import { useAppStore } from "@/store/useAppStore";

jest.mock("@/store/useAppStore", () => ({
  useAppStore: jest.fn(),
}));

jest.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-testid="glass-card" className={className}>{children}</div>
  ),
}));

const mockUseAppStore = useAppStore as unknown as ReturnType<typeof jest.fn>;

describe("AnalysisPreview", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: null,
        isAnalyzing: false,
        finishedAgents: [],
      };
      return selector(state);
    });
  });

  it("renders glass card", () => {
    render(<AnalysisPreview />);
    expect(screen.getByTestId("glass-card")).toBeInTheDocument();
  });

  it("shows '输入仓库地址开始分析' when idle", () => {
    render(<AnalysisPreview />);
    expect(screen.getByText("输入仓库地址开始分析")).toBeInTheDocument();
  });

  it("shows '正在分析中，请稍候...' when analyzing", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: null,
        isAnalyzing: true,
        finishedAgents: [],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("正在分析中，请稍候...")).toBeInTheDocument();
  });

  it("renders complexity from finalResult", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: {
            health_score: 85,
            complexity: "Medium",
            test_coverage: 60,
            maintainability: "A",
          },
          code_parser: {
            total_files: 150,
          },
        },
        isAnalyzing: false,
        finishedAgents: ["suggestion"],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("Medium")).toBeInTheDocument();
  });

  it("renders maintenance score label based on health score", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: {
            health_score: 85,
            complexity: "Low",
            test_coverage: 80,
            maintainability: "A",
          },
          code_parser: { total_files: 50 },
        },
        isAnalyzing: false,
        finishedAgents: [],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    // health_score 85 >= 80 → "A-"
    expect(screen.getByText("A-")).toBeInTheDocument();
  });

  it("shows correct insight text for High complexity", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: { health_score: 40, complexity: "High", test_coverage: 20, maintainability: "C" },
          code_parser: {},
        },
        isAnalyzing: false,
        finishedAgents: ["quality"],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("项目复杂度较高，建议优先处理架构耦合问题")).toBeInTheDocument();
  });

  it("shows correct insight text for Medium complexity", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: { health_score: 70, complexity: "Medium", test_coverage: 50, maintainability: "B+" },
          code_parser: {},
        },
        isAnalyzing: false,
        finishedAgents: ["quality"],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("项目结构合理，可针对性进行模块优化")).toBeInTheDocument();
  });

  it("shows correct insight text for Low complexity", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: { health_score: 90, complexity: "Low", test_coverage: 80, maintainability: "A+" },
          code_parser: {},
        },
        isAnalyzing: false,
        finishedAgents: ["quality"],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("项目维护性良好，建议关注依赖风险")).toBeInTheDocument();
  });

  it("renders file count from code_parser result", () => {
    mockUseAppStore.mockImplementation((selector) => {
      const state = {
        finalResult: {
          quality: { health_score: 80, complexity: "Low", test_coverage: 60, maintainability: "A" },
          code_parser: { total_files: 200, total_functions: 150 },
        },
        isAnalyzing: false,
        finishedAgents: [],
      };
      return selector(state);
    });

    render(<AnalysisPreview />);
    expect(screen.getByText("~200 文件")).toBeInTheDocument();
  });
});
