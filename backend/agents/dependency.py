"""DependencyAgent — 分析项目依赖的版本、已知漏洞和安全风险。

支持两种工作模式：
  - 内存模式（GitHub API）：传入 file_contents，Agent 内部过滤出依赖配置文件
  - 本地模式：传入 repo_path，从磁盘扫描依赖文件

风险评估策略：
  - KNOWN_HIGH：直接执行系统命令/读取敏感信息的包（eval、child_process、ssh2...）
  - KNOWN_MEDIUM：已弃用/有历史漏洞的包（request、lodash、moment...）
  - SUSPICIOUS_PATTERNS：可疑代码模式（exec、system、subprocess...）
  - 未锁定版本、file: 协议依赖、远程 URL 依赖均标记为 medium 风险
"""
import asyncio
import json
import logging
import os
import re
from typing import AsyncGenerator

from .base_agent import AgentEvent, BaseAgent, _make_event

_logger = logging.getLogger("gitintel")


class DependencyAgent(BaseAgent):
    """解析依赖配置文件，结合已知漏洞数据库评估风险。"""

    name = "dependency"

    async def stream(
        self,
        repo_path: str,
        branch: str = "main",
        file_contents: dict[str, str] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """解析依赖配置文件，评估风险。

        Args:
            repo_path: 仓库标识（owner/repo）。
            branch: 分支名。
            file_contents: 可选，GitHub API 直接返回的文件内容字典；
                          若不提供则从 repo_path 目录读取（本地开发兼容）。
        """
        yield _make_event(self.name, "status", "正在扫描依赖文件…", 10, None)

        if file_contents is not None:
            dep_files = [
                {"name": os.path.basename(p), "path": p, "type": self._detect_dep_type(p), "content": c}
                for p, c in file_contents.items()
                if self._is_dep_file(p)
            ]
            dep_names = [os.path.basename(p) for p in file_contents]
            _logger.info(f"[DependencyAgent] 内存模式: {len(file_contents)} 个文件传入，已过滤到 {len(dep_files)} 个依赖文件")
            _logger.debug(f"[DependencyAgent] 所有文件 basename: {dep_names}")
            _logger.debug(f"[DependencyAgent] 通过 _is_dep_file 的文件: {[d['name'] for d in dep_files]}")
        else:
            dep_files = await self._find_dep_files(repo_path)
            _logger.info(f"[DependencyAgent] 本地模式: {len(dep_files)} 个依赖文件")

        if not dep_files:
            yield _make_event(
                self.name, "result", "未找到依赖文件",
                100, {"total": 0, "scanned": 0, "high": 0, "medium": 0, "low": 0, "deps": []}
            )
            return

        yield _make_event(
            self.name, "progress",
            f"发现 {len(dep_files)} 个依赖文件，开始解析…", 30, None
        )

        all_deps = await self._parse_all_deps(dep_files)
        _logger.info(f"[DependencyAgent] 解析完成: {len(all_deps)} 个依赖项")
        yield _make_event(
            self.name, "progress",
            f"共解析 {len(all_deps)} 个依赖，正在评估风险…", 60, None
        )

        risk_assessment = self._assess_risk(all_deps)
        yield _make_event(
            self.name, "progress", "风险评估完成…", 85, None
        )

        result = {
            "total": risk_assessment.get("total", len(all_deps)),
            "scanned": risk_assessment.get("scanned", len(all_deps)),
            "high": risk_assessment["high"],
            "medium": risk_assessment["medium"],
            "low": risk_assessment["low"],
            "risk_level": risk_assessment["risk_level"],
            "summary": risk_assessment["summary"],
            "outdated_deps": risk_assessment.get("outdated_deps", []),
            "deps": risk_assessment.get("deps", []),
        }

        yield _make_event(
            self.name, "result", "依赖风险扫描完成",
            100, result
        )

    # ─── 内部实现 ───────────────────────────────────────────────

    @staticmethod
    def _detect_dep_type(path: str) -> str:
        """根据文件路径判断包管理器类型。"""
        name = os.path.basename(path)
        types = {
            "package.json": "npm", "package-lock.json": "npm",
            "pnpm-lock.yaml": "npm", "yarn.lock": "npm",
            "requirements.txt": "pip", "requirements-dev.txt": "pip",
            "Pipfile": "pipenv", "pyproject.toml": "poetry",
            "poetry.lock": "poetry", "go.mod": "go", "go.sum": "go",
            "Cargo.toml": "cargo", "Gemfile": "bundler",
            "composer.json": "composer", "pom.xml": "maven",
            "build.gradle": "gradle", "bun.lockb": "bun",
        }
        return types.get(name, "unknown")

    @staticmethod
    def _is_dep_file(path: str) -> bool:
        """判断路径是否指向依赖配置文件（排除 lock 文件和第三方依赖目录）。"""
        name = os.path.basename(path)
        # lock 文件不解析（太大），只解析 manifest 文件
        if name in {
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
            "poetry.lock", "go.sum", "bun.lockb",
        }:
            return False
        return name in {
            "package.json",
            "requirements.txt", "requirements-dev.txt",
            "Pipfile", "pyproject.toml",
            "go.mod", "Cargo.toml",
            "Gemfile", "composer.json",
            "pom.xml", "build.gradle",
        }

    @staticmethod
    async def _find_dep_files(root: str) -> list[dict]:
        """返回 {name, path} 列表，列出所有依赖配置文件。"""
        DEP_FILES = {
            "package.json": "npm",
            "pnpm-lock.yaml": "npm",
            "yarn.lock": "npm",
            "package-lock.json": "npm",
            "requirements.txt": "pip",
            "requirements-dev.txt": "pip",
            "Pipfile": "pipenv",
            "pyproject.toml": "poetry",
            "poetry.lock": "poetry",
            "go.mod": "go",
            "go.sum": "go",
            "Cargo.toml": "cargo",
            "Gemfile": "bundler",
            "composer.json": "composer",
            "pom.xml": "maven",
            "build.gradle": "gradle",
            "bun.lockb": "bun",
        }

        def _do() -> list[dict]:
            results = []
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in {
                    "node_modules", ".git", "__pycache__", ".venv", "venv",
                    "dist", "build", ".next", ".nuxt", "target",
                }]
                for fname in files:
                    if fname in DEP_FILES:
                        results.append({
                            "name": fname,
                            "path": os.path.join(dirpath, fname),
                            "type": DEP_FILES[fname],
                        })
            return results

        return await asyncio.to_thread(_do)

    @staticmethod
    async def _parse_all_deps(files: list[dict]) -> list[dict]:
        """解析所有依赖文件，返回依赖项列表。files 中的 content 为 GitHub 传来的文件内容。"""
        all_deps: list[dict] = []

        for info in files:
            try:
                deps = DependencyAgent._parse_content(
                    info.get("content", ""),
                    info.get("type", "unknown"),
                    info.get("name", os.path.basename(info.get("path", ""))),
                )
                all_deps.extend(deps)
                _logger.debug(f"[DependencyAgent] 解析 {info.get('name')}: 获得 {len(deps)} 个依赖")
            except Exception as e:
                _logger.warning(f"[DependencyAgent] 解析 {info.get('name')} 失败: {e}")

        return all_deps

    @staticmethod
    def _parse_content(content: str, dep_type: str, file_name: str) -> list[dict]:
        """解析依赖文件内容，返回依赖项列表。"""
        deps: list[dict] = []

        if not content:
            return deps

        if dep_type == "npm":
            try:
                data = json.loads(content)
                for section in ["dependencies", "devDependencies", "peerDependencies"]:
                    for name, ver in data.get(section, {}).items():
                        deps.append({
                            "name": name, "version": ver,
                            "type": section, "manager": "npm",
                        })
            except (json.JSONDecodeError, KeyError):
                pass

        elif dep_type == "pip":
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # 支持 pkg==1.2.3, pkg>=1.2, pkg~=1.0 等格式
                m = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:\[.*?\])?(?:==|>=|<=|~=|!=|>|<).*$", line)
                if m:
                    name = m.group(1)
                    ver = re.split(r"[=<>!~]", line)[-1].strip()
                    deps.append({"name": name, "version": ver, "type": "dependencies", "manager": "pip"})

        elif dep_type == "poetry":
            try:
                data = json.loads(content)
                for section in ["dependencies", "dev-dependencies"]:
                    raw = data.get("tool", {}).get("poetry", {}).get(section, {})
                    for name, spec in raw.items():
                        ver = spec if isinstance(spec, str) else (spec.get("version", "*") if isinstance(spec, dict) else "*")
                        deps.append({"name": name, "version": ver, "type": section, "manager": "poetry"})
            except (json.JSONDecodeError, KeyError, TypeError):
                # TOML 格式兜底
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("[") and "dependencies" in line.lower():
                        continue
                    m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*=\s*[\"\']([^\"\']+)[\"\']", line)
                    if m:
                        deps.append({"name": m.group(1), "version": m.group(2), "type": "dependencies", "manager": "poetry"})
        elif dep_type == "pipenv":
            section = ""
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    continue
                if section in ("packages", "dev-packages") and "=" in line:
                    name, ver = line.split("=", 1)
                    deps.append({"name": name.strip(), "version": ver.strip(), "type": section, "manager": "pipenv"})

        elif dep_type == "go":
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("require ("):
                    continue
                m = re.match(r"^\s*([a-zA-Z0-9_\-\./]+)\s+v?([0-9]", line)
                if m:
                    deps.append({"name": m.group(1), "version": m.group(2), "type": "require", "manager": "go"})

        elif dep_type == "cargo":
            in_deps = False
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped == "[dependencies]" or line_stripped.startswith("[dependencies."):
                    in_deps = True
                    continue
                if line_stripped.startswith("["):
                    in_deps = False
                if in_deps:
                    m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*=\s*[\"']?(.+?)[\"']?\s*(?:,)?$", line_stripped)
                    if m:
                        deps.append({"name": m.group(1), "version": m.group(2), "type": "dependencies", "manager": "cargo"})

        elif dep_type == "composer":
            try:
                data = json.loads(content)
                for section in ["require", "require-dev"]:
                    for name, ver in data.get(section, {}).items():
                        deps.append({"name": name, "version": ver, "type": section, "manager": "composer"})
            except (json.JSONDecodeError, KeyError):
                pass

        elif dep_type in ("maven", "gradle"):
            # 简化解析：提取 group:artifact:version 格式
            for line in content.splitlines():
                m = re.search(r"<groupId>(.+?)</groupId>.*?<artifactId>(.+?)</artifactId>.*?<version>(.+?)</version>", line + content, re.DOTALL)
                if m:
                    deps.append({
                        "name": f"{m.group(2)}",
                        "version": m.group(3),
                        "group": m.group(1),
                        "type": "dependencies",
                        "manager": dep_type,
                    })

        return deps

    @staticmethod
    def _assess_risk(deps: list[dict]) -> dict:
        """综合评估依赖风险，包含 npm/pip 特定规则和安全特征库。"""
        high, medium, low = 0, 0, 0
        high_deps: list[dict] = []
        medium_deps: list[dict] = []
        summary: list[str] = []

        KNOWN_HIGH: dict[str, str] = {
            "eval": "eval() 执行任意代码",
            "child_process": "可执行系统命令",
            "shelljs": "可执行系统 shell 命令",
            "systeminformation": "可读取敏感系统信息",
            "ssh2": "SSH 连接管理，可能泄露凭证",
            "neo4j-driver": "数据库连接，可能泄露凭证",
            "mysql": "MySQL 连接器，可能泄露凭证",
            "mysql2": "MySQL 连接器，可能泄露凭证",
            "pg": "PostgreSQL 连接器，可能泄露凭证",
            "redis": "Redis 连接器，可能泄露凭证",
            "mongodb": "MongoDB 连接器，可能泄露凭证",
            "fluent-logger": "日志发送，可能外泄敏感数据",
            "winreg": "Windows 注册表操作",
            "forever": "持久化运行，可能被滥用",
            "pm2": "进程管理，可能被滥用",
            "node-powershell": "PowerShell 执行",
            "node-fetch": "已弃用（推荐使用内置 fetch）",
        }
        KNOWN_MEDIUM: dict[str, str] = {
            "request": "已弃用，存在安全漏洞",
            "axios": "已知部分版本存在 SSRF 风险",
            "jquery": "DOM 操作，低版本存在 XSS",
            "lodash": "lodash < 4.17.21 存在原型污染漏洞",
            "underscore": "存在原型污染风险",
            "moment": "已停止维护，存在时区/解析漏洞",
            "http-server": "简易 HTTP 服务器，不适合生产",
            "nodemailer": "邮件发送，需确保配置正确防止滥用",
            "socket.io": "实时通信，需鉴权配置",
            "ws": "WebSocket，需鉴权配置",
        }
        OUTDATED_WARN: dict[str, str] = {
            "request": "request 已废弃（2020-02-11），建议迁移到 axios/fetch",
            "lodash": "lodash 版本过低，存在原型污染风险（建议 >= 4.17.21）",
            "moment": "moment 已停止维护（2022-09-11），建议迁移到 dayjs/date-fns",
            "jquery": "jQuery 在现代前端项目中通常可移除，减少依赖体积",
            "express": "Express 4.x 存在拒绝服务风险，建议升级",
            "graphql": "GraphQL 可能存在查询深度/复杂度风险",
            "mongoose": "MongoDB ODM，需关注注入风险",
        }
        SUSPICIOUS_PATTERNS: dict[str, str] = {
            "exec": "代码执行风险",
            "system": "系统命令执行风险",
            "child_process": "子进程执行风险",
            "os.system": "os.system 调用",
            "subprocess": "subprocess 调用",
            "eval(": "动态代码执行",
            "password": "密码处理相关",
            "secret": "密钥处理相关",
            "credential": "凭证处理相关",
            "token": "令牌处理相关",
        }
        no_version_deps: list[str] = []

        for dep in deps:
            name = dep.get("name", "")
            version = dep.get("version", "")
            lower_name = name.lower()

            risk = "low"
            risk_reason = ""

            for kw, reason in KNOWN_HIGH.items():
                if kw in lower_name:
                    risk = "high"
                    risk_reason = reason
                    break

            if risk == "low":
                for kw, reason in KNOWN_MEDIUM.items():
                    if kw in lower_name:
                        risk = "medium"
                        risk_reason = reason
                        break

            if risk == "low":
                for pat, reason in SUSPICIOUS_PATTERNS.items():
                    if pat in lower_name:
                        risk = "high"
                        risk_reason = reason
                        break

            if risk == "low":
                if not version or version in ("*", "latest", "x"):
                    risk = "medium"
                    risk_reason = "未锁定版本，可能引入不一致性或破坏性更新"
                    no_version_deps.append(name)

            if risk == "low" and dep.get("manager") == "npm":
                if version and (version.startswith("file:") or version.startswith("link:")):
                    risk = "medium"
                    risk_reason = f"本地路径依赖 '{version}' 在 CI/CD 或他人环境中可能失效"

            if risk == "low" and dep.get("manager") == "pip":
                if version and ("git+" in version or "http://" in version or "https://" in version):
                    risk = "medium"
                    risk_reason = f"直接从远程 URL 安装依赖可能引入安全风险"

            if risk == "low":
                for kw, reason in OUTDATED_WARN.items():
                    if kw in lower_name:
                        risk = "medium"
                        risk_reason = reason
                        break

            if risk == "high":
                high += 1
                high_deps.append({**dep, "risk_level": "high", "risk_reason": risk_reason})
            elif risk == "medium":
                medium += 1
                medium_deps.append({**dep, "risk_level": "medium", "risk_reason": risk_reason})
            else:
                low += 1

        total = len(deps)

        if high > 0:
            risk_level = "高危"
            top_names = ", ".join(d["name"] for d in high_deps[:3])
            summary.append(f"⚠️ {high} 个高危依赖需立即处理（{top_names}）")
        elif medium > total * 0.3:
            risk_level = "中等"
            summary.append(f"⚡ {medium} 个依赖存在中危风险，建议优先更新")
        elif medium > 0:
            risk_level = "低危"
        elif total > 0:
            risk_level = "极低"
        else:
            risk_level = "极低"

        outdated_specific: list[str] = []
        for dep in deps:
            for kw, reason in OUTDATED_WARN.items():
                if kw in dep.get("name", "").lower():
                    outdated_specific.append(f"{dep['name']}: {reason}")
        if outdated_specific:
            summary.extend(outdated_specific[:3])

        if no_version_deps:
            summary.append(f"⚡ {len(no_version_deps)} 个依赖未指定版本，建议锁定版本范围")

        all_risky = high_deps[:5] + medium_deps[:5]

        return {
            "high": high,
            "medium": medium,
            "low": low,
            "risk_level": risk_level,
            "summary": summary,
            "outdated_deps": outdated_specific[:5],
            "deps": all_risky,
            "total": total,
            "scanned": total,
        }

