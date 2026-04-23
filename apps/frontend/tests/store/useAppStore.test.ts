import { describe, it, expect, beforeEach } from "@jest/globals";
import { act, renderHook } from "@testing-library/react";
import { useAppStore } from "@/store/useAppStore";
import type { AgentEventData } from "@/store/useAppStore";

describe("useAppStore — Zustand state management", () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    useAppStore.getState().reset();
  });

  describe("initial state", () => {
    it("has correct initial values", () => {
      const state = useAppStore.getState();

      expect(state.isAnalyzing).toBe(false);
      expect(state.repoUrl).toBe("");
      expect(state.agentEvents).toEqual({});
      expect(state.finishedAgents).toEqual([]);
      expect(state.finalResult).toBe(null);
      expect(state.analysisResult).toBe(null);
      expect(state.error).toBe(null);
    });
  });

  describe("setIsAnalyzing", () => {
    it("updates isAnalyzing to true", () => {
      const { result } = renderHook(() => useAppStore());

      act(() => {
        result.current.setIsAnalyzing(true);
      });

      expect(useAppStore.getState().isAnalyzing).toBe(true);
    });

    it("updates isAnalyzing to false", () => {
      useAppStore.getState().setIsAnalyzing(true);

      act(() => {
        useAppStore.getState().setIsAnalyzing(false);
      });

      expect(useAppStore.getState().isAnalyzing).toBe(false);
    });
  });

  describe("setRepoUrl", () => {
    it("updates repoUrl", () => {
      const { result } = renderHook(() => useAppStore());

      act(() => {
        result.current.setRepoUrl("https://github.com/test/repo");
      });

      expect(useAppStore.getState().repoUrl).toBe("https://github.com/test/repo");
    });
  });

  describe("pushAgentEvent", () => {
    it("adds an agent event to agentEvents", () => {
      const event: AgentEventData = {
        type: "status",
        agent: "quality",
        message: "Scanning...",
        percent: 10,
      };

      act(() => {
        useAppStore.getState().pushAgentEvent(event);
      });

      expect(useAppStore.getState().agentEvents["quality"]).toEqual(event);
    });

    it("updates agentEvent when same agent fires again", () => {
      const event1: AgentEventData = {
        type: "status",
        agent: "quality",
        message: "Scanning...",
        percent: 10,
      };
      const event2: AgentEventData = {
        type: "progress",
        agent: "quality",
        message: "Analyzing...",
        percent: 50,
      };

      act(() => {
        useAppStore.getState().pushAgentEvent(event1);
        useAppStore.getState().pushAgentEvent(event2);
      });

      expect(useAppStore.getState().agentEvents["quality"]).toEqual(event2);
    });

    it("adds agent to finishedAgents on result event", () => {
      const event: AgentEventData = {
        type: "result",
        agent: "quality",
        message: "Done",
        percent: 100,
        data: { health_score: 85 },
      };

      act(() => {
        useAppStore.getState().pushAgentEvent(event);
      });

      expect(useAppStore.getState().finishedAgents).toContain("quality");
    });

    it("does not duplicate agents in finishedAgents", () => {
      const event1: AgentEventData = { type: "result", agent: "quality", percent: 100 };
      const event2: AgentEventData = { type: "result", agent: "quality", percent: 100 };

      act(() => {
        useAppStore.getState().pushAgentEvent(event1);
        useAppStore.getState().pushAgentEvent(event2);
      });

      expect(useAppStore.getState().finishedAgents.filter(a => a === "quality")).toHaveLength(1);
    });

    it("stores finalResult on final_result agent result event", () => {
      const event: AgentEventData = {
        type: "result",
        agent: "final_result",
        percent: 100,
        data: { quality: { health_score: 90 }, total: 5 },
      };

      act(() => {
        useAppStore.getState().pushAgentEvent(event);
      });

      expect(useAppStore.getState().finalResult).toEqual({ quality: { health_score: 90 }, total: 5 });
    });

    it("stores last result data in analysisResult", () => {
      const event: AgentEventData = {
        type: "result",
        agent: "quality",
        percent: 100,
        data: { score: 85 },
      };

      act(() => {
        useAppStore.getState().pushAgentEvent(event);
      });

      expect(useAppStore.getState().analysisResult).toEqual({ score: 85 });
    });
  });

  describe("setFinalResult", () => {
    it("updates finalResult directly", () => {
      const { result } = renderHook(() => useAppStore());

      act(() => {
        result.current.setFinalResult({ quality: { health_score: 95 } });
      });

      expect(useAppStore.getState().finalResult).toEqual({ quality: { health_score: 95 } });
    });
  });

  describe("setAnalysisResult", () => {
    it("updates analysisResult", () => {
      const { result } = renderHook(() => useAppStore());

      act(() => {
        result.current.setAnalysisResult({ total: 10 });
      });

      expect(useAppStore.getState().analysisResult).toEqual({ total: 10 });
    });
  });

  describe("setError", () => {
    it("sets error and disables isAnalyzing", () => {
      useAppStore.getState().setIsAnalyzing(true);

      act(() => {
        useAppStore.getState().setError("Analysis failed");
      });

      expect(useAppStore.getState().error).toBe("Analysis failed");
      expect(useAppStore.getState().isAnalyzing).toBe(false);
    });
  });

  describe("reset", () => {
    it("resets all state to initial values", () => {
      // Populate state with some values
      act(() => {
        useAppStore.getState().setIsAnalyzing(true);
        useAppStore.getState().setRepoUrl("https://github.com/test/repo");
        useAppStore.getState().pushAgentEvent({ type: "result", agent: "quality", percent: 100 });
        useAppStore.getState().setFinalResult({ quality: {} });
        useAppStore.getState().setError("some error");
      });

      act(() => {
        useAppStore.getState().reset();
      });

      const state = useAppStore.getState();
      expect(state.isAnalyzing).toBe(false);
      expect(state.repoUrl).toBe("");
      expect(state.agentEvents).toEqual({});
      expect(state.finishedAgents).toEqual([]);
      expect(state.finalResult).toBe(null);
      expect(state.analysisResult).toBe(null);
      expect(state.error).toBe(null);
    });
  });
});
