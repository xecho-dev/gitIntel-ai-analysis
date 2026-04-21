"""TechStackAgent — 深度识别项目技术栈，解析 package.json / requirements.txt 等配置文件。"""
import asyncio
import json
import os
import re
from pathlib import Path
from typing import AsyncGenerator

from .base_agent import AgentEvent, BaseAgent, _make_event


# 常见框架/库的特征标识
_FRAMEWORKS: dict[str, list[str]] = {
    "React": ["react", "react-dom", "react-native"],
    "Vue": ["vue", "@vue/", "nuxt"],
    "Angular": ["@angular/core", "@angular/common"],
    "Next.js": ["next"],
    "Express": ["express"],
    "FastAPI": ["fastapi"],
    "Fastify": ["fastify"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring Boot": ["spring-boot", "org.springframework.boot"],
    "Spring": ["org.springframework"],
    "Rails": ["rails"],
    "Laravel": ["illuminate", "laravel"],
    "Svelte": ["svelte"],
    "NestJS": ["@nestjs/"],
    "Vite": ["vite"],
    "Webpack": ["webpack"],
    "PyTorch": ["torch"],
    "TensorFlow": ["tensorflow"],
    "LangChain": ["langchain", "langchain-core", "langchain-anthropic"],
    "LangGraph": ["langgraph", "langgraph-sdk"],
    "LangServe": ["langserve"],
    "Anthropic SDK": ["anthropic"],
    "OpenAI SDK": ["openai"],
    "Redis": ["redis"],
    "PostgreSQL": ["psycopg2", "pg", "postgres"],
    "MongoDB": ["pymongo", "mongodb"],
    "GraphQL": ["graphql", "@apollo/", "@graphql/"],
    "tRPC": ["@trpc/"],
    "Prisma": ["@prisma/client", "prisma"],
    "tqdm": ["tqdm"],
    "Pydantic": ["pydantic"],
    "Celery": ["celery"],
    "Redis (JS)": ["ioredis"],
    "Tailwind CSS": ["tailwindcss", "@tailwindcss/"],
    "Sass/SCSS": ["sass", "node-sass"],
    "Bootstrap": ["bootstrap"],
    "Material UI": ["@mui/", "@material-ui/"],
    "shadcn/ui": ["lucide-react", "clsx", "tailwind-merge"],
    "Radix UI": ["@radix-ui/"],
    "Zustand": ["zustand"],
    "Redux": ["redux", "@reduxjs/"],
    "Jotai": ["jotai"],
    "Pinia": ["pinia"],
    "React Query": ["@tanstack/react-query"],
    "SWR": ["swr"],
    "NumPy": ["numpy"],
    "Pandas": ["pandas"],
    "Scikit-learn": ["scikit-learn", "sklearn"],
    "OpenCV": ["cv2", "opencv"],
    "SQLAlchemy": ["sqlalchemy"],
    "Alembic": ["alembic"],
    "pytest": ["pytest"],
    "unittest": ["unittest"],
    "Vitest": ["vitest"],
    "Jest": ["jest"],
    "Playwright": ["playwright", "@playwright/test"],
    "Storybook": ["@storybook/"],
    "ESLint": ["eslint"],
    "Prettier": ["prettier"],
    "Ruff": ["ruff"],
    "Black": ["black"],
    "Mypy": ["mypy"],
    "Tox": ["tox"],
    "Poetry": ["poetry"],
    "Hatch": ["hatch"],
    "UV": ["uv"],
}


class TechStackAgent(BaseAgent):
    """深度扫描仓库，识别完整技术栈和依赖信息。"""

    name = "tech_stack"

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """分析配置文件（package.json, requirements.txt 等），识别技术栈。

        Args:
            repo_path: 仓库标识（owner/repo）。
            branch: 分支名。
            file_contents: 可选，GitHub API 直接返回的文件内容字典；
                           若不提供则从 repo_path 目录读取（本地开发兼容）。
        """
        yield _make_event(self.name, "status", "正在扫描配置文件…", 10, None)

        try:
            if file_contents is not None:
                configs = await self._collect_configs_from_memory(file_contents)
            else:
                configs = await self._collect_configs(repo_path)
        except Exception as exc:
            yield _make_event(self.name, "error", f"配置文件扫描失败: {exc}", 0, None)
            return

        yield _make_event(
            self.name, "progress",
            f"发现 {len(configs)} 个配置文件，开始解析…", 40, None
        )

        try:
            analysis = await self._analyze_configs(configs, repo_path)
        except Exception as exc:
            yield _make_event(self.name, "error", f"配置解析失败: {exc}", 0, None)
            return

        yield _make_event(self.name, "progress", "技术栈分析完成，正在生成报告…", 80, None)

        yield _make_event(self.name, "result", "技术栈识别完成", 100, analysis)

    # ─── 内部实现 ───────────────────────────────────────────────

    @staticmethod
    async def _collect_configs_from_memory(file_contents: dict[str, str]) -> dict[str, dict]:
        """从内存字典中收集配置文件（GitHub API 模式）。"""
        CONFIG_FILES = frozenset({
            "package.json", "package-lock.json", "pnpm-lock.yaml",
            "requirements.txt", "requirements-dev.txt", "Pipfile", "pyproject.toml",
            "Cargo.toml", "go.mod", "Gemfile", "composer.json",
            "pom.xml", "build.gradle", "build.gradle.kts",
            "docker-compose.yml", "docker-compose.yaml",
            "Dockerfile", "Makefile", "tox.ini", "setup.cfg",
            "tsconfig.json", "vite.config.ts", "vite.config.js",
            "next.config.js", "next.config.ts", ".eslintrc",
            ".prettierrc", "tailwind.config.ts", "tailwind.config.js",
            "vercel.json", "netlify.toml",
        })
        return {
            fname: {"path": fname, "content": content}
            for fname, content in file_contents.items()
            if os.path.basename(fname) in CONFIG_FILES
            or os.path.basename(fname).startswith("README")
        }

    @staticmethod
    async def _collect_configs(root: str) -> dict[str, dict]:
        """收集所有配置文件内容。"""
        CONFIG_FILES = [
            "package.json", "package-lock.json", "pnpm-lock.yaml",
            "requirements.txt", "requirements-dev.txt", "Pipfile", "pyproject.toml",
            "Cargo.toml", "go.mod", "Gemfile", "composer.json",
            "pom.xml", "build.gradle", "build.gradle.kts",
            "docker-compose.yml", "docker-compose.yaml",
            "Dockerfile", "Makefile", "tox.ini", "setup.cfg",
            "tsconfig.json", "vite.config.ts", "vite.config.js",
            "next.config.js", "next.config.ts", ".eslintrc*",
            ".prettierrc*", "tailwind.config.ts", "tailwind.config.js",
            "vercel.json", "netlify.toml",
        ]

        def _do() -> dict[str, dict]:
            results: dict[str, dict] = {}
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in {
                    "node_modules", ".git", "__pycache__", ".venv", "venv",
                    "dist", "build", ".next", ".nuxt",
                }]
                for fname in files:
                    if fname in CONFIG_FILES:
                        fpath = os.path.join(dirpath, fname)
                        try:
                            results[fname] = {
                                "path": fpath.replace("\\", "/"),
                                "content": TechStackAgent._read_config(fpath),
                            }
                        except Exception:
                            pass
            return results

        return await asyncio.to_thread(_do)

    @staticmethod
    def _read_config(path: str) -> str:
        """读取配置文件，处理二进制文件。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()

    @staticmethod
    async def _analyze_configs(configs: dict[str, dict], repo_path: str) -> dict:
        """解析收集到的配置文件，输出结构化技术栈信息。"""
        def _do() -> dict:
            frameworks: list[str] = []
            languages: list[str] = []
            infrastructure: list[str] = []
            dev_tools: list[str] = []
            raw_deps: dict[str, list[str]] = {}
            dependency_count = 0
            dev_dependency_count = 0
            package_manager = "unknown"

            for fname, info in configs.items():
                content = info["content"]
                base = os.path.basename(fname)  # 兼容磁盘路径和 GitHub API 全路径

                # ── package.json ─────────────────────────────────
                if base in ("package.json", "pnpm-lock.yaml"):
                    package_manager = "pnpm" if base == "pnpm-lock.yaml" else "npm"
                    try:
                        data = json.loads(content)
                        deps = data.get("dependencies", {})
                        dev_deps = data.get("devDependencies", {})
                        all_deps = {**deps, **dev_deps}

                        dependency_count += len(deps)
                        dev_dependency_count += len(dev_deps)

                        for dep, ver in all_deps.items():
                            for framework, keywords in _FRAMEWORKS.items():
                                if any(kw in dep for kw in keywords):
                                    if framework not in frameworks:
                                        frameworks.append(framework)
                                    break

                        # 检测语言
                        if "ts-node" in all_deps or "typescript" in all_deps:
                            if "TypeScript" not in languages:
                                languages.append("TypeScript")
                        elif "node" in all_deps:
                            if "JavaScript" not in languages:
                                languages.append("JavaScript")

                        # 检测包管理器
                        if "@rushstack/" in all_deps or "rush" in all_deps:
                            package_manager = "rush"
                    except json.JSONDecodeError:
                        pass

                # ── requirements.txt / Pipfile ──────────────────
                elif base in ("requirements.txt", "requirements-dev.txt"):
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            dep = re.split(r"[=<>!~]", line)[0].strip()
                            if dep:
                                dependency_count += 1
                                for framework, keywords in _FRAMEWORKS.items():
                                    if any(kw in dep.lower() for kw in keywords):
                                        if framework not in frameworks:
                                            frameworks.append(framework)
                                        break
                            if "Python" not in languages:
                                languages.append("Python")

                elif base == "Pipfile":
                    if "Python" not in languages:
                        languages.append("Python")
                    for framework, keywords in _FRAMEWORKS.items():
                        if any(kw in content.lower() for kw in keywords):
                            if framework not in frameworks:
                                frameworks.append(framework)

                elif base == "pyproject.toml":
                    if "Python" not in languages:
                        languages.append("Python")
                    for framework, keywords in _FRAMEWORKS.items():
                        if any(kw in content.lower() for kw in keywords):
                            if framework not in frameworks:
                                frameworks.append(framework)

                # ── go.mod ──────────────────────────────────────
                elif base == "go.mod":
                    if "Go" not in languages:
                        languages.append("Go")
                    for framework, keywords in _FRAMEWORKS.items():
                        if any(kw in content for kw in keywords):
                            if framework not in frameworks:
                                frameworks.append(framework)

                # ── Cargo.toml ─────────────────────────────────
                elif base == "Cargo.toml":
                    if "Rust" not in languages:
                        languages.append("Rust")
                    for framework, keywords in _FRAMEWORKS.items():
                        if any(kw in content for kw in keywords):
                            if framework not in frameworks:
                                frameworks.append(framework)

                # ── Gemfile ────────────────────────────────────
                elif base == "Gemfile":
                    if "Ruby" not in languages:
                        languages.append("Ruby")
                    for framework, keywords in _FRAMEWORKS.items():
                        if any(kw in content.lower() for kw in keywords):
                            if framework not in frameworks:
                                frameworks.append(framework)

                # ── composer.json ───────────────────────────────
                elif base == "composer.json":
                    if "PHP" not in languages:
                        languages.append("PHP")
                    try:
                        data = json.loads(content)
                        for dep in list(data.get("require", {})) + list(data.get("require-dev", {})):
                            for framework, keywords in _FRAMEWORKS.items():
                                if any(kw in dep for kw in keywords):
                                    if framework not in frameworks:
                                        frameworks.append(framework)
                    except json.JSONDecodeError:
                        pass

                # ── Docker ─────────────────────────────────────
                elif base in ("docker-compose.yml", "docker-compose.yaml", "Dockerfile"):
                    if "Docker" not in infrastructure:
                        infrastructure.append("Docker")

                # ── infrastructure ─────────────────────────────
                elif base == "Makefile":
                    if "Make" not in dev_tools:
                        dev_tools.append("Make")

                elif base == "tsconfig.json":
                    if "TypeScript" not in languages:
                        languages.append("TypeScript")

                elif base in ("next.config.js", "next.config.ts"):
                    if "Next.js" not in frameworks:
                        frameworks.insert(0, "Next.js")

                elif base in ("vite.config.ts", "vite.config.js"):
                    if "Vite" not in frameworks:
                        frameworks.insert(0, "Vite")

                elif "tailwind.config" in base:
                    if "Tailwind CSS" not in frameworks:
                        frameworks.append("Tailwind CSS")

            # README 关键词扫描（磁盘模式）
            readme_path = os.path.join(repo_path, "README.md")
            if os.path.isfile(readme_path):
                try:
                    readme = TechStackAgent._read_config(readme_path)[:2000]
                    for kw in ["LLM", "AI", "GPT", "Claude", "OpenAI", "LangChain", "LangGraph"]:
                        if kw in readme and kw not in frameworks:
                            frameworks.append(kw)
                except Exception:
                    pass
            # README 关键词扫描（内存模式：configs 中可能已有 README.md）
            for fname, info in configs.items():
                if os.path.basename(fname).lower().startswith("readme"):
                    readme_content = info["content"][:2000]
                    for kw in ["LLM", "AI", "GPT", "Claude", "OpenAI", "LangChain", "LangGraph"]:
                        if kw in readme_content and kw not in frameworks:
                            frameworks.append(kw)
                    break  # 只处理第一个 README

            return {
                "languages": languages,
                "frameworks": frameworks,
                "infrastructure": infrastructure,
                "dev_tools": dev_tools,
                "package_manager": package_manager,
                "dependency_count": dependency_count,
                "dev_dependency_count": dev_dependency_count,
                "config_files_found": list(configs.keys()),
            }

        return await asyncio.to_thread(_do)
