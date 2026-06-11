# GitIntel AI Analysis

<div align="center">

![GitIntel Banner](images/home.png)

### AI-Powered GitHub Repository Analysis

Deep scan any public repository, automatically generate architecture quality, code health, dependency risks, and optimization suggestions.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15-black)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-blue)](https://langchain-ai.github.io/langgraph/)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)

</div>

---

## Features

| Feature | Description |
|---------|-------------|
| **ReAct Agent** | Reasoning + Acting pattern for intelligent code exploration |
| **Architecture Analysis** | Parse directory structure, generate architecture diagrams |
| **Code Quality** | Scan common issues, health score with 5-dimension LLM scoring |
| **Dependency Risk** | Analyze `package.json` / `requirements.txt`, identify outdated dependencies |
| **Optimization Suggestions** | RAG-enhanced actionable refactoring recommendations |
| **SSE Streaming** | Real-time analysis progress, no waiting for full results |
| **Reflection Mechanism** | Self-correction with confidence scoring and 4-dimension evaluation |
| **GitHub OAuth** | NextAuth.js v5 + GitHub OAuth |
| **Health Score** | Comprehensive 5-dimension scoring with visual cards |
| **AI Assistant** | RAG-powered intelligent Q&A with multi-layer memory system |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 15)                                      │
│  App Router + Tailwind CSS                                  │
│  Zustand State Management                                   │
│  Port: 3000                                                 │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP / SSE Streaming
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  BFF Layer (Next.js Route Handler)                           │
│  apps/frontend/app/api/**/route.ts                          │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent Layer (FastAPI + LangGraph)                          │
│  ReAct Agents + RAG + Streaming                             │
│  Port: 8000                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Frontend

| Category | Technology |
|----------|------------|
| Framework | Next.js 15 (App Router) |
| UI Framework | Umi.js 4 (Admin) |
| React | React 19 |
| State Management | Zustand |
| Charts | Recharts |
| Styling | Tailwind CSS v3/v4 |
| Authentication | NextAuth.js v5 (GitHub Provider) |
| Database Client | `asyncpg` (PostgreSQL) |

### Backend

| Category | Technology |
|----------|------------|
| Framework | FastAPI 0.115+ |
| Workflow | LangGraph |
| Code Analysis | Tree-sitter (Python, TypeScript, etc.) |
| Vector Store | ChromaDB + LangChain |
| LLM Integration | LangChain + DashScope |
| Database ORM | `asyncpg` (native PostgreSQL driver) |
| Deployment | uvicorn (ASGI) |

---

## Project Structure

```
gitintel-ai-analysis/                     # Root (pnpm workspace)
│
├── apps/                                  # Application layer
│   ├── frontend/                          # Next.js Frontend (Port 3000)
│   │   ├── app/                           # Next.js App Router
│   │   │   ├── page.tsx                   # Landing page
│   │   │   ├── layout.tsx                 # Root layout
│   │   │   ├── workspace/                # Main workspace
│   │   │   ├── login/                    # Login page
│   │   │   ├── history/                  # History page
│   │   │   ├── account/                  # Account page
│   │   │   └── api/                      # BFF Route Handlers
│   │   │       ├── analyze/              # Analysis endpoint
│   │   │       ├── history/              # History endpoints
│   │   │       ├── auth/                 # Auth endpoints
│   │   │       ├── chat/                 # Chat endpoints
│   │   │       └── pr/                   # PR endpoints
│   │   ├── components/                    # React components
│   │   │   ├── agents/                    # Agent result cards
│   │   │   ├── layout/                    # Layout components
│   │   │   ├── ui/                       # Shared UI components
│   │   │   └── landing/                  # Landing page sections
│   │   ├── store/                         # Zustand stores
│   │   │   ├── useAppStore.ts            # App state
│   │   │   └── useChatStore.ts           # Chat state
│   │   └── lib/                           # Utilities
│   │       ├── api.ts                     # BFF API client (SSE)
│   │       ├── auth.ts                   # NextAuth config
│   │       ├── postgres_client.ts       # PostgreSQL client
│   │       └── utils.ts                   # Helper functions
│   │
│   └── admin/                             # Umi.js Admin (Port 3001)
│       ├── src/
│       │   ├── pages/                    # Admin pages
│       │   │   ├── dashboard.tsx         # Dashboard
│       │   │   ├── users.tsx             # User management
│       │   │   ├── analysis-history.tsx  # Analysis history
│       │   │   ├── audit.tsx             # Audit logs
│       │   │   └── settings.tsx          # Settings
│       │   ├── layouts/                   # Admin layouts
│       │   ├── components/                # Admin components
│       │   ├── services/                  # API services
│       │   └── models/                    # Umi models
│       └── .umirc.ts                      # Umi config
│
├── backend/                               # FastAPI Agent Layer (Port 8000)
│   ├── agents/                            # Agent implementations
│   │   ├── react/                        # ReAct pattern agents
│   │   │   ├── base_agent.py            # Base ReAct agent
│   │   │   ├── repo_loader_agent.py     # Repo loading agent
│   │   │   ├── suggestion_agent.py      # Suggestion agent
│   │   │   ├── reflection_agent.py      # Reflection mechanism
│   │   │   ├── explorers.py             # Explorer orchestrator
│   │   │   ├── tool_wrapper.py         # Tool wrapper
│   │   │   └── error_loop_detector.py  # Error detection
│   │   └── legacy/                      # Legacy implementations
│   │       ├── architecture.py          # Architecture agent
│   │       ├── quality.py               # Quality agent
│   │       ├── dependency.py            # Dependency agent
│   │       ├── tech_stack.py           # Tech stack detection
│   │       ├── code_parser.py          # Code parser
│   │       └── optimization.py          # Optimization agent
│   │
│   ├── graph/                            # LangGraph workflow
│   │   ├── state.py                    # SharedState definition
│   │   ├── analysis_graph.py           # Main workflow orchestration
│   │   └── executor.py                 # Workflow executor
│   │
│   ├── routers/                          # FastAPI routers
│   │   ├── analysis.py                 # Analysis endpoints
│   │   ├── history.py                  # History endpoints
│   │   ├── user.py                     # User endpoints
│   │   ├── chat.py                     # Chat endpoints
│   │   ├── pr.py                       # PR generation endpoints
│   │   ├── git_ops.py                 # Git operations
│   │   ├── export.py                   # Export endpoints
│   │   └── admin/                      # Admin endpoints
│   │
│   ├── tools/                            # Agent tools
│   │   ├── code_tools.py              # Code analysis tools
│   │   ├── github_tools.py            # GitHub API tools
│   │   ├── rag_tools.py              # RAG tools
│   │   └── chat_tools.py             # Chat tools
│   │
│   ├── rag/                              # RAG system
│   │   ├── query_processor.py         # Query processing
│   │   ├── generator.py               # Response generation
│   │   ├── retriever.py              # Retrieval
│   │   ├── context_processor.py      # Context processing
│   │   └── post_processor.py         # Post-processing
│   │
│   ├── memory/                           # Vector memory
│   │   ├── chromadb_store.py         # ChromaDB integration
│   │   ├── embeddings.py             # Embedding generation
│   │   └── multi_memory.py           # Multi-memory manager
│   │
│   ├── services/                         # Business services
│   │   ├── database.py              # Database operations
│   │   ├── pdf_service.py           # PDF generation
│   │   ├── image_generation.py      # Image generation
│   │   ├── github_pr_service.py     # GitHub PR service
│   │   ├── git_service.py           # Git service
│   │   └── langsmith_service.py     # LangSmith tracing
│   │
│   ├── schemas/                          # Pydantic models
│   │   ├── request.py               # Request models
│   │   ├── response.py              # Response models
│   │   ├── history.py               # History models
│   │   └── chat.py                  # Chat models
│   │
│   ├── middleware/                       # FastAPI middleware
│   │   ├── auth.py                 # Authentication
│   │   └── admin_auth.py          # Admin authentication
│   │
│   ├── utils/                            # Utilities
│   │   ├── llm_factory.py         # LLM factory
│   │   ├── code_parser.py         # Code parser utilities
│   │   ├── tree_filter.py         # Tree filtering
│   │   └── tool_result.py         # Tool result processing
│   │
│   ├── eval/                              # Evaluation
│   │   ├── rag_eval.py            # RAG evaluation
│   │   └── ragas_evaluator.py    # RAGAs evaluator
│   │
│   ├── tests/                            # Tests
│   │   ├── test_agents/           # Agent tests
│   │   ├── test_graph/            # Graph tests
│   │   └── test_api/              # API tests
│   │
│   ├── main.py                        # FastAPI entry point
│   └── pyproject.toml               # Python dependencies
│
├── packages/                             # Shared packages
│   ├── types/                           # Shared TypeScript types
│   │   └── index.ts                   # Type definitions
│   │                                    # (AnalyzeRequest, AgentEvent,
│   │                                    #  AnalysisResult, HistoryItem, etc.)
│   └── ui/                             # Shared UI components
│       └── src/
│           ├── button.tsx
│           ├── dialog.tsx
│           ├── tooltip.tsx
│           ├── avatar.tsx
│           ├── skeleton.tsx
│           ├── collapsible.tsx
│           └── resizable.tsx
│
├── deploy/                              # Deployment configs
│   └── ...
│
├── Dockerfile.frontend                 # Frontend Docker image
├── Dockerfile.admin                     # Admin Docker image
├── Dockerfile.backend                  # Backend Docker image
├── docker-compose.yml                  # Docker Compose config
├── pnpm-workspace.yaml                # pnpm workspace config
├── turbo.json                         # Turborepo pipeline
└── package.json                       # Root workspace metadata
```

---

## Core Agents

| Agent | Responsibility |
|-------|----------------|
| `ReActRepoLoaderAgent` | Intelligent file tree loading with ReAct reasoning |
| `ReActSuggestionAgent` | RAG-enhanced optimization suggestions |
| `ReActReflectionAgent` | Self-correction with confidence scoring |
| `ExplorerOrchestrator` | Parallel multi-explorer coordination |
| `QualityExplorer` | Code quality analysis (complexity, duplication, etc.) |
| `TechStackExplorer` | Technology stack detection |
| `DependencyExplorer` | Dependency risk analysis |

### Reflection Mechanism

The `ReActReflectionAgent` provides 4-dimension evaluation for analysis quality:

| Dimension | Description |
|-----------|-------------|
| **Completeness** | Is the analysis missing important code parts? |
| **Accuracy** | Are conclusions evidence-based? |
| **Actionability** | Are suggestions specific and executable? |
| **Risk Assessment** | Potential misjudgments or risks? |

Output includes confidence scores (0.0-1.0) and improvement suggestions for re-running agents.

---

## AI Assistant (RAG Chat)

The built-in AI Assistant provides intelligent Q&A powered by RAG pipeline with multi-layer memory system.

### RAG Pipeline Architecture

```
User Input
     │
     ▼
┌─────────────────────┐
│ 1. Query Rewrite    │  ⭐ Intent classification, keyword extraction
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 2. Vector Retrieval │  ← Initial retrieval
└──────────┬──────────┘
           │
      No results?
           │
       ┌───┴───┐
       │       │
      Yes      No
       │       │
       ▼       ▼
┌─────────────────┐   ┌─────────────────────┐
│ 3. HyDE Fallback│   │ Context Processing  │
│ (Hypothetical   │   │                    │
│  Document)      │   │                    │
└────────┬────────┘   └─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ 4. Context          │
│    Processing        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 5. LLM Streaming    │
│    Generation        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ 6. Multi-Layer      │
│    Memory Save       │
└─────────────────────┘
```

### Multi-Layer Memory System

| Layer | Description | Scope |
|-------|-------------|--------|
| **Short-term** | Conversation window memory | Current session |
| **Long-term** | Semantic memory (ChromaDB) | Cross-session |
| **Profile** | User preferences and patterns | Persistent |

### RAG Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `QueryProcessor` | `rag/query_processor.py` | Intent classification, keyword expansion |
| `MultiStrategyRetriever` | `rag/retriever.py` | Vector + keyword retrieval + RRF fusion |
| `ContextProcessor` | `rag/context_processor.py` | Context filtering, token budget control |
| `RAGGenerator` | `rag/generator.py` | LLM streaming generation |
| `MultiLayerMemory` | `memory/multi_memory.py` | Multi-layer memory management |
| `RAGASEvaluator` | `eval/ragas_evaluator.py` | Quality metrics (faithfulness, answer_relevancy) |

### Chat API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat/sessions` | Create chat session |
| `GET` | `/api/chat/sessions` | List all sessions |
| `GET` | `/api/chat/sessions/{id}/messages` | Get session messages |
| `POST` | `/api/chat/send` | Send message (SSE streaming) |
| `DELETE` | `/api/chat/sessions/{id}` | Delete session |

---

## Analysis Flow

```
User Input (GitHub URL)
        │
        ▼
┌───────────────────┐
│  BFF Route Handler │  apps/frontend/app/api/analyze/route.ts
└─────────┬─────────┘
          │ HTTP POST
          ▼
┌───────────────────┐
│  FastAPI /analyze │  backend/routers/analysis.py
└─────────┬─────────┘
          │ SSE Stream
          ▼
┌───────────────────┐
│  LangGraph        │  backend/graph/analysis_graph.py
│  Workflow         │
└─────────┬─────────┘
          │
    ┌─────┼─────┬─────────────┐
    ▼     ▼     ▼             ▼
┌───────┐ ┌───┐ ┌──────────┐ ┌──────────┐
│ Repo  │ │Exp│ │Explorer   │ │Suggestion │
│Loader │ │   │ │Orchestrator│ │  Agent   │
└───┬───┘ └───┘ └────┬─────┘ └────┬─────┘
    │                │            │
    └───────┬────────┴────────────┘
            │ SSE Events
            ▼
┌───────────────────┐
│  Reflection       │  4-dimension evaluation
│  Agent            │  (Completeness, Accuracy,
└─────────┬─────────┘  Actionability, Risk)
          │ Confidence Score
          ▼
┌───────────────────┐
│  Streaming Results │  Real-time UI Updates
└───────────────────┘
```

### Stage 1: Repository Loading (ReAct)
- `ReActRepoLoaderAgent` analyzes file tree with ReAct reasoning
- P0/P1/P2 file classification based on importance
- Progressive file loading based on analysis needs

### Stage 2: Code Structure Parsing
- Tree-sitter AST parsing for Python, TypeScript, etc.
- Function/class/import extraction
- Semantic chunking for better context

### Stage 3: Parallel Exploration
- `ExplorerOrchestrator` coordinates multiple explorers
- `QualityExplorer`: Complexity, duplication, code smells
- `TechStackExplorer`: Languages, frameworks, infrastructure
- `DependencyExplorer`: Version risks, vulnerabilities

### Stage 4: Architecture Evaluation
- Component relationship analysis
- Architecture pattern recognition
- Hot spot identification

### Stage 5: Optimization Suggestions
- `ReActSuggestionAgent` generates actionable recommendations
- RAG-enhanced context awareness
- Priority-based suggestion ranking

### Stage 6: Reflection (Self-Correction)
- `ReActReflectionAgent` reviews all outputs
- 4-dimension evaluation with confidence scoring
- Decides if agents need re-running

---

## Environment Variables

### Frontend (`apps/frontend/.env.local`)

```env
# PostgreSQL
DATABASE_URL=postgresql://gitintel:password@localhost:5432/gitintel

# NextAuth v5
AUTH_SECRET=your_auth_secret
AUTH_URL=http://localhost:3000
AUTH_GITHUB_ID=your_github_client_id
AUTH_GITHUB_SECRET=your_github_client_secret

# Agent API
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Backend (`backend/.env`)

```env
# GitHub Token (for API access)
GITHUB_TOKEN=ghp_your_token

# OpenAI / DashScope
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus

# PostgreSQL
DATABASE_URL=postgresql://gitintel:password@localhost:5432/gitintel

# Token Control
MAX_OUTPUT_TOKENS=1024
EXPLORER_MAX_ITERATIONS=4
REPO_LOADER_MAX_ITERATIONS=8
TOOL_RESULT_TRUNCATE=2000
```

> Reference `deploy.env.example` for all available variables.

---

## Quick Start

### Prerequisites

- Node.js >= 18
- pnpm >= 9
- Python 3.12+
- Supabase project
- GitHub OAuth App

### 1. Install Dependencies

```bash
git clone https://github.com/xecho-dev/GitIntel-AI-Analysis.git
cd gitintel-ai-analysis
pnpm install
```

### 2. Configure Environment

```bash
cp deploy.env.example deploy.env        # Root directory
cp apps/frontend/.env.example apps/frontend/.env.local
```

Fill in all required variables in `deploy.env` and `.env.local`.

### 3. Start Development

```bash
# Start all services (recommended)
pnpm dev

# Or start individually
pnpm dev:frontend   # Frontend → http://localhost:3000
pnpm dev:admin      # Admin → http://localhost:3001
pnpm dev:backend    # Backend → http://localhost:8000
```

---

## API Documentation

### Core Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/health` | Health check | Public |
| `POST` | `/api/analyze` | Start repository analysis (SSE) | JWT |
| `GET` | `/api/analysis/{id}` | Get analysis result | JWT |
| `GET` | `/api/history` | Paginated analysis history | JWT |
| `POST` | `/api/history/save` | Save analysis result | JWT |
| `DELETE` | `/api/history/{id}` | Delete history item | JWT |
| `POST` | `/api/chat/send` | Send chat message | JWT |
| `POST` | `/api/pr/generate` | Generate PR description | JWT |
| `POST` | `/api/pr/create` | Create GitHub PR | JWT |

### SSE Event Format

Each event is a JSON line:

```json
{"type": "status", "agent": "fetch_tree_classify", "message": "Loading repository...", "percent": 10, "data": null}
{"type": "progress", "agent": "load_p0", "message": "Loading critical files...", "percent": 30, "data": null}
{"type": "result", "agent": "code_parser_final", "message": "Analysis complete", "percent": 100, "data": {...}}
{"type": "error", "agent": "quality", "message": "Analysis failed: ...", "percent": 0, "data": null}
data: [DONE]
```

`type` values: `status` | `progress` | `result` | `error`

---

## Deployment

### Docker Compose (Recommended)

```bash
docker compose up -d --build
```

### Manual Deployment

#### Frontend

```bash
cd apps/frontend
pnpm install
pnpm build
docker build -f Dockerfile.frontend -t gitintel-frontend .
docker run -p 3000:3000 gitintel-frontend
```

#### Admin

```bash
cd apps/admin
pnpm install
pnpm build
docker build -f Dockerfile.admin -t gitintel-admin .
docker run -p 3001:3001 gitintel-admin
```

#### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Shared Types

All cross-layer types are defined in `packages/types/index.ts`:

```typescript
// Request
export interface AnalyzeRequest {
  repoUrl: string;
  branch?: string;
}

// SSE Event
export interface AgentEvent {
  type: "status" | "progress" | "result" | "error";
  agent: AgentName;
  message?: string;
  percent?: number;
  data?: unknown;
}

// Analysis Result
export interface AnalysisResult {
  repoLoader?: { ... };
  codeParser?: { ... };
  techStack?: { ... };
  quality: QualityResult;
  dependency: DependencyResult;
  architecture: ArchitectureResult;
  suggestion: OptimizationResult;
}
```

---

## Development Guide

### Adding a New Agent

1. Create agent file in `backend/agents/react/` (e.g., `security_agent.py`)
2. Inherit from `BaseReActAgent`, implement `run()` method
3. Register in `backend/graph/analysis_graph.py`
4. Frontend SSE consumer updates automatically

### Token Consumption Control

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_OUTPUT_TOKENS` | 1024 | Max LLM output per call |
| `EXPLORER_MAX_ITERATIONS` | 4 | Max ReAct explorer iterations |
| `REPO_LOADER_MAX_ITERATIONS` | 8 | Max repo loader iterations |
| `TOOL_RESULT_TRUNCATE` | 2000 | Max chars per tool result |

---

## License

MIT
