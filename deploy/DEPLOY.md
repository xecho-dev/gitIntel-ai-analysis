# GitIntel 部署指南

本文档详细说明如何将 GitIntel 前后端部署到自托管服务器。

## 目录

- [服务器要求](#服务器要求)
- [部署架构](#部署架构)
- [第一步：服务器初始化](#第一步服务器初始化)
- [第二步：配置 GitHub Secrets](#第二步配置-github-secrets)
- [第三步：推送代码触发部署](#第三步推送代码触发部署)
- [常用运维命令](#常用运维命令)
- [故障排查](#故障排查)
- [回滚操作](#回滚操作)

---

## 服务器要求

| 配置项 | 要求 |
|--------|------|
| 操作系统 | Alibaba Cloud Linux 3 / RHEL 8+ / CentOS 8+ / Ubuntu 22.04 |
| CPU | 2 核以上 |
| 内存 | 4GB 以上（推荐 8GB） |
| 磁盘 | 20GB 以上 |
| 网络 | 固定公网 IP（你的服务器：47.80.59.132） |

---

## 部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                      GitHub                                │
│   push → GitHub Actions CI → Build → Deploy                 │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS (443)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (服务器)                           │
│                   反向代理 / 负载均衡                        │
└──────────────┬──────────────────────────────┬────────────────┘
               │                              │
               │ 3000                          │ 8000
               ▼                              ▼
┌─────────────────────────┐    ┌──────────────────────────────┐
│  Frontend (Next.js)     │    │  Backend (FastAPI)          │
│  Docker 容器            │◄──►│  Docker 容器                 │
│  端口: 3000             │    │  端口: 8000                 │
└─────────────────────────┘    └──────────────────────────────┘
         │
         │ 内部网络
         ▼
┌─────────────────────────┐
│  Supabase (云服务)       │
│  数据库 / 认证           │
└─────────────────────────┘
```

---

## 第一步：服务器初始化

SSH 登录你的服务器，执行初始化脚本：

```bash
# 下载并运行初始化脚本
wget https://raw.githubusercontent.com/YOUR_USERNAME/gitintel-ai-analysis/main/deploy/init-server.sh
chmod +x init-server.sh
sudo ./init-server.sh
```

脚本会自动安装：
- Docker 和 Docker Compose
- Nginx
- Certbot（用于 HTTPS）
- 配置防火墙

> **注意**：将 `YOUR_USERNAME` 替换为你的 GitHub 用户名。

### 手动初始化（可选）

如果想手动安装，可以逐条执行以下命令：

```bash
# 安装 Docker（使用阿里云镜像加速）
curl -fsSL https://get.docker.com | sh

# 安装 Docker Compose
yum install -y docker-compose-plugin

# 启动 Docker
systemctl start docker
systemctl enable docker

# 安装 Nginx
yum install -y nginx
systemctl enable nginx
```

---

## 第二步：配置 GitHub Secrets

在 GitHub 仓库页面（`Settings > Secrets and variables > Actions`）添加以下 Secrets：

### 必需配置

| Secret 名称 | 说明 | 示例值 |
|-------------|------|--------|
| `SERVER_HOST` | 服务器 IP | `47.80.59.132` |
| `SERVER_USER` | SSH 用户名 | `root`（或新建 deploy 用户） |
| `SERVER_SSH_KEY` | SSH 私钥 | `-----BEGIN OPENSSH PRIVATE KEY-----...` |

### 配置 SSH 密钥

1. **在本地生成密钥对**（如果还没有）：

```bash
ssh-keygen -t ed25519 -C "github-actions@gitintel" -f github-actions-key
```

2. **将公钥添加到服务器**：

```bash
# 方法一：复制公钥到服务器
ssh-copy-id -i github-actions-key.pub root@47.80.59.132

# 方法二：手动添加
cat github-actions-key.pub | ssh root@47.80.59.132 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

3. **将私钥添加到 GitHub Secrets**：

```bash
# 查看私钥内容
cat github-actions-key
```

复制私钥内容，粘贴到 GitHub Secrets 的 `SERVER_SSH_KEY` 中。

### 应用配置

| Secret 名称 | 说明 | 示例值 |
|-------------|------|--------|
| `FRONTEND_URL` | 前端访问地址 | `http://47.80.59.132`（生产环境建议用域名 + HTTPS） |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-...` |
| `SUPABASE_URL` | Supabase 项目 URL | `https://xxx.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase 匿名密钥 | `eyJhbGci...` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase Service Role 密钥 | `eyJhbGci...` |
| `SUPABASE_JWT_SECRET` | Supabase JWT Secret | `your-jwt-secret` |
| `GITHUB_TOKEN` | GitHub Personal Access Token（用于访问私有仓库） | `ghp_...` |

### 获取 GitHub Token

1. 访问 GitHub Settings > Developer settings > Personal access tokens
2. 生成新令牌（Fine-grained tokens），需要的权限：
   - `Contents: Read-only`（拉取私有仓库）
3. 将令牌添加到 GitHub Secrets 为 `GITHUB_TOKEN`

---

## 第三步：推送代码触发部署

配置完成后，每次推送到 `main` 分支都会自动触发部署：

```bash
git checkout main
git merge your-feature-branch  # 合并功能分支
git push origin main
```

### CI/CD 流程

```
push to main
    │
    ▼
┌─────────────────────────────┐
│  GitHub Actions CI          │
│  ├── Lint (ESLint + Ruff)  │
│  ├── Type Check             │
│  ├── Test (Jest + Pytest)   │
│  └── Build Docker Images    │
└────────────┬────────────────┘
             │ 全部通过
             ▼
┌─────────────────────────────┐
│  GitHub Actions Deploy      │
│  ├── Push to GHCR           │
│  ├── SSH to Server          │
│  ├── Pull Docker Images     │
│  ├── Restart Containers     │
│  └── Health Check           │
└─────────────────────────────┘
```

---

## 常用运维命令

### 查看服务状态

```bash
# SSH 登录服务器
ssh root@47.80.59.132

# 进入部署目录
cd /opt/gitintel

# 查看容器状态
docker compose ps

# 查看容器健康状态
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"
```

### 查看日志

```bash
# 查看所有容器日志
docker compose logs

# 实时跟踪后端日志
docker compose logs -f backend

# 查看最近 100 行前端日志
docker compose logs --tail=100 frontend

# 查看特定时间的日志
docker compose logs --since="2024-01-01T00:00:00" backend
```

### 重启服务

```bash
# 重启所有服务
docker compose restart

# 只重启后端
docker compose restart backend

# 强制重建并重启（代码更新后）
docker compose up -d --force-recreate --build
```

### 更新服务

```bash
# SSH 登录服务器
ssh root@47.80.59.132

# 进入部署目录
cd /opt/gitintel

# 拉取最新镜像并重启
docker compose pull
docker compose up -d
```

---

## 故障排查

### 容器启动失败

```bash
# 查看详细错误
docker compose up

# 查看后端容器日志
docker compose logs backend

# 进入后端容器调试
docker compose exec backend bash
```

### 端口被占用

```bash
# 检查端口占用
lsof -i :3000
lsof -i :8000

# 如果需要释放端口
kill -9 $(lsof -t -i :3000)
```

### 清理 Docker

```bash
# 清理未使用的镜像
docker image prune -a

# 清理未使用的容器和网络
docker system prune -a

# 清理所有未使用资源
docker system prune -a --volumes
```

### 数据库连接问题

检查 Supabase 配置是否正确：

```bash
# 进入后端容器
docker compose exec backend bash

# 测试 Supabase 连接
python -c "import os; print(os.getenv('SUPABASE_URL'))"
```

---

## 回滚操作

### 方法一：通过 Docker 镜像回滚

```bash
# SSH 登录服务器
ssh root@47.80.59.132
cd /opt/gitintel

# 查看可用的历史镜像
docker images | grep gitintel

# 回滚到上一个版本
docker compose pull
docker compose up -d

# 或者指定特定版本
docker pull ghcr.io/YOUR_USERNAME/gitintel-ai-analysis/backend:<commit-sha>
docker pull ghcr.io/YOUR_USERNAME/gitintel-ai-analysis/frontend:<commit-sha>
docker compose up -d
```

### 方法二：通过 Git 回滚

```bash
# 在本地回滚到上一个稳定版本
git revert HEAD  # 创建新提交撤销上次更改
# 或者
git reset --hard <previous-commit-sha>
git push --force
```

---

## 安全加固（可选）

### 1. 创建专用部署用户

```bash
# 创建用户
useradd -m -s /bin/bash deploy

# 添加到 Docker 组
usermod -aG docker deploy

# 配置 SSH
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh

# 复制公钥
cat github-actions-key.pub >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy

# 更新 GitHub Secrets 中的 SERVER_USER 为 "deploy"
```

### 2. 配置 HTTPS

```bash
# 安装 EPEL 仓库（如果还没有）
yum install -y epel-release

# 安装 certbot
yum install -y certbot python3-certbot-nginx

# 申请证书（需要域名解析到服务器）
certbot --nginx -d your-domain.com -d www.your-domain.com

# 自动续期
certbot renew --dry-run
```

### 3. 限制 SSH 访问

编辑 `/etc/ssh/sshd_config`：

```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

---

## 监控建议

可以使用以下工具监控服务：

1. **Uptime Kuma** - 自托管的服务监控
2. **Grafana + Prometheus** - 容器监控
3. **Sentry** - 前端错误追踪

---

## 获取帮助

如果遇到问题：

1. 查看 GitHub Actions 日志
2. 查看服务器容器日志
3. 在 GitHub Issues 提交问题
