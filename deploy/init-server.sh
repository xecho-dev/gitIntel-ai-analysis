#!/bin/bash
# ============================================================
# GitIntel 服务器初始化脚本
#
# 功能：在一台全新的 Linux 服务器上一键安装所有依赖
#
# 使用方法：
#   1. 以 root 用户登录服务器
#   2. 下载此脚本：
#      wget https://raw.githubusercontent.com/YOUR_USERNAME/gitintel-ai-analysis/main/deploy/init-server.sh
#      chmod +x init-server.sh
#   3. 运行：
#      ./init-server.sh
#
# 适用于：Alibaba Cloud Linux 3 / RHEL 8+ / CentOS 8+
# ============================================================

set -e

echo "============================================"
echo "  GitIntel 服务器初始化脚本"
echo "============================================"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用 root 用户运行此脚本"
    echo "   sudo ./init-server.sh"
    exit 1
fi

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ========== 1. 更新系统 ==========
log_info "1/6 更新系统包..."
yum update -y -q
log_info "系统更新完成 ✓"

# ========== 2. 安装基础软件 ==========
log_info "2/6 安装基础软件（Docker, Docker Compose, Nginx, Certbot）..."

# 安装基础工具
yum install -y -q \
    curl \
    wget \
    git \
    vim \
    htop \
    unzip \
    ca-certificates \
    gnupg \
    yum-utils

# 安装 Docker（使用阿里云镜像加速）
if ! command -v docker &> /dev/null; then
    log_info "安装 Docker..."

    # 添加 Docker CE 镜像源（阿里云）
    yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo

    # 安装 Docker
    yum install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # 启动并设置开机自启
    systemctl start docker
    systemctl enable docker
    log_info "Docker 安装完成 ✓"
else
    log_info "Docker 已安装 ✓"
fi

# 安装 Nginx
if ! command -v nginx &> /dev/null; then
    log_info "安装 Nginx..."
    # Alibaba Cloud Linux 3 默认带有 nginx
    yum install -y -q nginx
    systemctl enable nginx
    log_info "Nginx 安装完成 ✓"
else
    log_info "Nginx 已安装 ✓"
fi

# 安装 Certbot（Let's Encrypt）
if ! command -v certbot &> /dev/null; then
    log_info "安装 Certbot..."

    # 安装 EPEL 仓库（Certbot 依赖）
    if ! rpm -q epel-release &> /dev/null; then
        yum install -y -q epel-release
    fi

    # 安装 Certbot
    yum install -y -q certbot python3-certbot-nginx
    log_info "Certbot 安装完成 ✓"
else
    log_info "Certbot 已安装 ✓"
fi

# ========== 3. 配置防火墙 ==========
log_info "3/6 配置防火墙（firewalld）..."

# 检查 firewalld 是否存在
if command -v firewall-cmd &> /dev/null; then
    # 开放端口
    firewall-cmd --permanent --add-port=22/tcp
    firewall-cmd --permanent --add-port=80/tcp
    firewall-cmd --permanent --add-port=443/tcp
    firewall-cmd --permanent --add-port=3000/tcp
    firewall-cmd --permanent --add-port=8000/tcp

    # 重载防火墙
    firewall-cmd --reload
    log_info "firewalld 防火墙配置完成 ✓"
elif command -v ufw &> /dev/null; then
    # 如果安装了 ufw（Ubuntu 环境兼容）
    UFW_rules=(
        "22/tcp"
        "80/tcp"
        "443/tcp"
        "3000/tcp"
        "8000/tcp"
    )
    for rule in "${UFW_rules[@]}"; do
        ufw allow $rule 2>/dev/null || true
    done
    ufw --force enable 2>/dev/null || true
    log_info "UFW 防火墙配置完成 ✓"
else
    log_warn "未检测到防火墙服务，跳过防火墙配置"
    log_info "请手动确保以下端口已开放：22, 80, 443, 3000, 8000"
fi

# ========== 4. 创建部署目录 ==========
log_info "4/6 创建部署目录..."

DEPLOY_PATH="/opt/gitintel"
mkdir -p $DEPLOY_PATH/logs
mkdir -p $DEPLOY_PATH/data

# 创建 docker-compose.yml 示例
cat > $DEPLOY_PATH/docker-compose.yml.example << 'EOF'
# 请复制此文件为 docker-compose.yml，并填入实际的环境变量
version: "3.8"

services:
  frontend:
    image: ghcr.io/YOUR_USERNAME/gitintel-ai-analysis/frontend:latest
    container_name: gitintel-frontend
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      NODE_ENV: production
      AUTH_TRUST_HOST: "true"
    env_file:
      - .env
    networks:
      - gitintel-net
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  backend:
    image: ghcr.io/YOUR_USERNAME/gitintel-ai-analysis/backend:latest
    container_name: gitintel-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      FRONTEND_URL: https://your-domain.com
    networks:
      - gitintel-net
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

networks:
  gitintel-net:
    driver: bridge
EOF

# 创建 .env 示例文件
cat > $DEPLOY_PATH/.env.example << 'EOF'
# Supabase 配置
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret

# OpenAI 配置
OPENAI_API_KEY=sk-your-openai-key
OPENAI_BASE_URL=https://api.openai.com/v1

# GitHub Token（访问私有仓库）
GITHUB_TOKEN=ghp_xxx

# 前端访问地址（用于后端 CORS 白名单）
FRONTEND_URL=https://your-domain.com
EOF

log_info "部署目录创建完成 ✓"
log_info "  部署路径: $DEPLOY_PATH"
log_info "  示例配置: $DEPLOY_PATH/docker-compose.yml.example"
log_info "  环境变量: $DEPLOY_PATH/.env.example"

# ========== 5. 配置 Nginx ==========
log_info "5/6 配置 Nginx..."

# 备份默认配置
if [ -f /etc/nginx/nginx.conf ]; then
    cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak
fi

# 创建 GitIntel Nginx 配置
cat > /etc/nginx/conf.d/gitintel.conf << 'EOF'
upstream gitintel_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

upstream gitintel_frontend {
    server 127.0.0.1:3000;
    keepalive 32;
}

server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://gitintel_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://gitintel_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_cache off;
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    location /health {
        proxy_pass http://gitintel_backend/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        access_log off;
    }
}
EOF

# 测试 Nginx 配置
nginx -t

# 重载 Nginx
systemctl reload nginx
log_info "Nginx 配置完成 ✓"

# ========== 6. 完成 ==========
log_info "6/6 服务器初始化完成！"
echo ""
echo "============================================"
echo -e "${GREEN}  🎉 初始化成功！${NC}"
echo "============================================"
echo ""
echo "📝 下一步操作："
echo ""
echo "1️⃣  配置环境变量："
echo "   cp $DEPLOY_PATH/.env.example $DEPLOY_PATH/.env"
echo "   vim $DEPLOY_PATH/.env  # 填入实际值"
echo ""
echo "2️⃣  配置 GitHub Secrets（在 GitHub 仓库 Settings > Secrets）："
echo "   - SERVER_HOST: $HOSTNAME"
echo "   - SERVER_USER: root"
echo "   - SERVER_SSH_KEY: 服务器 SSH 私钥"
echo "   - FRONTEND_URL: http://\$HOSTNAME  (或你的域名)"
echo "   - OPENAI_API_KEY: 你的 OpenAI API Key"
echo "   - SUPABASE_* 相关配置"
echo ""
echo "3️⃣  推送代码到 main 分支，GitHub Actions 将自动部署"
echo ""
echo "📊 常用命令："
echo "   cd $DEPLOY_PATH && docker compose ps              # 查看容器状态"
echo "   cd $DEPLOY_PATH && docker compose logs            # 查看日志"
echo "   cd $DEPLOY_PATH && docker compose restart         # 重启服务"
echo ""
echo "🔒 安全建议："
echo "   - 考虑使用非 root 用户运行容器"
echo "   - 配置 HTTPS（certbot --nginx -d your-domain.com）"
echo "   - 限制 SSH 访问（仅允许密钥登录）"
echo ""