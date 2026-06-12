#!/bin/bash
set -e

DEPLOY_PATH="__DEPLOY_PATH__"
SERVER_USER="__SERVER_USER__"
REGISTRY="__REGISTRY__"
REPO_LOWER="__REPO_LOWER__"
FRONTEND_IMAGE="__FRONTEND_IMAGE__"
ADMIN_IMAGE="__ADMIN_IMAGE__"
BACKEND_IMAGE="__BACKEND_IMAGE__"
REGISTRY_USERNAME="__REGISTRY_USERNAME__"
REGISTRY_TOKEN="__REGISTRY_TOKEN__"
export DEPLOY_PATH SERVER_USER REGISTRY REPO_LOWER FRONTEND_IMAGE ADMIN_IMAGE BACKEND_IMAGE REGISTRY_USERNAME REGISTRY_TOKEN
export POSTGRES_PASSWORD="__POSTGRES_PASSWORD__"
export OPENAI_API_KEY="__OPENAI_API_KEY__"
export OPENAI_BASE_URL="__OPENAI_BASE_URL__"
export GITHUB_TOKEN="__GITHUB_TOKEN__"
export FRONTEND_URL="__FRONTEND_URL__"
export AUTH_SECRET="__AUTH_SECRET__"
export AUTH_URL="__FRONTEND_URL__"
export AUTH_GITHUB_ID="__AUTH_GITHUB_ID__"
export AUTH_GITHUB_SECRET="__AUTH_GITHUB_SECRET__"
export LANGSMITH_TRACING="__LANGSMITH_TRACING__"
export LANGSMITH_ENDPOINT="__LANGSMITH_ENDPOINT__"
export LANGSMITH_PROJECT="__LANGSMITH_PROJECT__"
export LANGSMITH_API_KEY="__LANGSMITH_API_KEY__"
export DASHVECTOR_API_KEY="__DASHVECTOR_API_KEY__"
export DASHVECTOR_ENDPOINT="__DASHVECTOR_ENDPOINT__"
export DASHVECTOR_COLLECTION="__DASHVECTOR_COLLECTION__"
COMMIT_SHORT="__COMMIT_SHORT__"

echo "========== 开始部署 GitIntel =========="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Commit: $COMMIT_SHORT"

sudo mkdir -p "$DEPLOY_PATH"
sudo chown -R "$SERVER_USER:$SERVER_USER" "$DEPLOY_PATH"
cd "$DEPLOY_PATH"
mv /tmp/gitintel.env .env

# ── PostgreSQL 服务 ─────────────────────────────────────────
cat > postgres-compose.yml << 'PGCOMPOSE'
services:
  postgres:
    image: postgres:16-alpine
    container_name: gitintel-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: gitintel
      POSTGRES_USER: gitintel
      POSTGRES_PASSWORD: POSTGRES_PASSWORD_PLACEHOLDER
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - gitintel-net
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "gitintel", "-d", "gitintel"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
PGCOMPOSE

sed -i "s|POSTGRES_PASSWORD_PLACEHOLDER|$POSTGRES_PASSWORD|g" postgres-compose.yml

# ── 其余服务 ───────────────────────────────────────────────
cat > docker-compose.yml << 'DOCKERCOMPOSE'
services:
  postgres:
    image: postgres:16-alpine
    container_name: gitintel-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: gitintel
      POSTGRES_USER: gitintel
      POSTGRES_PASSWORD: POSTGRES_PASSWORD_PLACEHOLDER
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - gitintel-net
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "gitintel", "-d", "gitintel"]
      interval: 5s
      timeout: 5s
      retries: 10

  frontend:
    image: FRONTEND_IMAGE_PLACEHOLDER
    container_name: gitintel-frontend
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      NODE_ENV: production
      AUTH_TRUST_HOST: "true"
      AUTH_URL: AUTH_URL_PLACEHOLDER
      AUTH_GITHUB_ID: AUTH_GITHUB_ID_PLACEHOLDER
      AUTH_GITHUB_SECRET: AUTH_GITHUB_SECRET_PLACEHOLDER
      AUTH_SECRET: AUTH_SECRET_PLACEHOLDER
    env_file:
      - .env
    networks:
      - gitintel-net
    depends_on:
      - backend
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  admin:
    image: ADMIN_IMAGE_PLACEHOLDER
    container_name: gitintel-admin
    restart: unless-stopped
    ports:
      - "3001:3001"
    environment:
      NODE_ENV: production
    networks:
      - gitintel-net
    depends_on:
      - backend
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:3001"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  backend:
    image: BACKEND_IMAGE_PLACEHOLDER
    container_name: gitintel-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql://gitintel:POSTGRES_PASSWORD_PLACEHOLDER@postgres:5432/gitintel
      FRONTEND_URL: FRONTEND_URL_PLACEHOLDER
      AUTH_SECRET: AUTH_SECRET_PLACEHOLDER
      LANGSMITH_TRACING: LANGSMITH_TRACING_PLACEHOLDER
      LANGSMITH_ENDPOINT: LANGSMITH_ENDPOINT_PLACEHOLDER
      LANGSMITH_PROJECT: LANGSMITH_PROJECT_PLACEHOLDER
      LANGSMITH_API_KEY: LANGSMITH_API_KEY_PLACEHOLDER
      DASHVECTOR_API_KEY: DASHVECTOR_API_KEY_PLACEHOLDER
      DASHVECTOR_ENDPOINT: DASHVECTOR_ENDPOINT_PLACEHOLDER
      DASHVECTOR_COLLECTION: DASHVECTOR_COLLECTION_PLACEHOLDER
    networks:
      - gitintel-net
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

networks:
  gitintel-net:
    driver: bridge

volumes:
  postgres_data:
DOCKERCOMPOSE

sed -i "s|POSTGRES_PASSWORD_PLACEHOLDER|$POSTGRES_PASSWORD|g" docker-compose.yml
sed -i "s|FRONTEND_IMAGE_PLACEHOLDER|$FRONTEND_IMAGE|g" docker-compose.yml
sed -i "s|ADMIN_IMAGE_PLACEHOLDER|$ADMIN_IMAGE|g" docker-compose.yml
sed -i "s|BACKEND_IMAGE_PLACEHOLDER|$BACKEND_IMAGE|g" docker-compose.yml
sed -i "s|FRONTEND_URL_PLACEHOLDER|$FRONTEND_URL|g" docker-compose.yml
sed -i "s|AUTH_URL_PLACEHOLDER|$AUTH_URL|g" docker-compose.yml
sed -i "s|AUTH_GITHUB_ID_PLACEHOLDER|$AUTH_GITHUB_ID|g" docker-compose.yml
sed -i "s|AUTH_GITHUB_SECRET_PLACEHOLDER|$AUTH_GITHUB_SECRET|g" docker-compose.yml
sed -i "s|AUTH_SECRET_PLACEHOLDER|$AUTH_SECRET|g" docker-compose.yml
sed -i "s|LANGSMITH_TRACING_PLACEHOLDER|$LANGSMITH_TRACING|g" docker-compose.yml
sed -i "s|LANGSMITH_ENDPOINT_PLACEHOLDER|$LANGSMITH_ENDPOINT|g" docker-compose.yml
sed -i "s|LANGSMITH_PROJECT_PLACEHOLDER|$LANGSMITH_PROJECT|g" docker-compose.yml
sed -i "s|LANGSMITH_API_KEY_PLACEHOLDER|$LANGSMITH_API_KEY|g" docker-compose.yml
sed -i "s|DASHVECTOR_API_KEY_PLACEHOLDER|$DASHVECTOR_API_KEY|g" docker-compose.yml
sed -i "s|DASHVECTOR_ENDPOINT_PLACEHOLDER|$DASHVECTOR_ENDPOINT|g" docker-compose.yml
sed -i "s|DASHVECTOR_COLLECTION_PLACEHOLDER|$DASHVECTOR_COLLECTION|g" docker-compose.yml

echo "正在配置 Nginx..."
if [ -f /etc/nginx/conf.d/gitintel.conf ]; then
  sudo cp /etc/nginx/conf.d/gitintel.conf /etc/nginx/conf.d/gitintel.conf.bak
fi
sudo cp /tmp/gitintel.conf /etc/nginx/conf.d/gitintel.conf

sudo nginx -t && sudo nginx -s reload || { echo "Nginx 配置失败，已回滚"; sudo cp /etc/nginx/conf.d/gitintel.conf.bak /etc/nginx/conf.d/gitintel.conf 2>/dev/null || true; sudo nginx -t && sudo nginx -s reload; exit 1; }
echo "Nginx 配置完成"

echo "正在拉取镜像..."
if docker pull "$FRONTEND_IMAGE" &>/dev/null; then
  echo "公开镜像，无需登录即可拉取"
  docker-compose pull
else
  echo "镜像拉取失败，尝试登录后再拉取..."
  echo "$REGISTRY_TOKEN" | docker login "$REGISTRY" -u "$REGISTRY_USERNAME" --password-stdin || { echo "Docker login 失败"; exit 1; }
  docker-compose pull
fi
echo "正在清理旧容器..."
docker stop gitintel-postgres gitintel-frontend gitintel-admin gitintel-backend 2>/dev/null || true
docker rm gitintel-postgres gitintel-frontend gitintel-admin gitintel-backend 2>/dev/null || true
echo "正在启动服务..."
docker-compose up -d
sleep 10

echo ""
echo "========== 容器状态 =========="
docker-compose ps

FRONTEND_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' gitintel-frontend 2>/dev/null)
ADMIN_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' gitintel-admin 2>/dev/null)
BACKEND_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' gitintel-backend 2>/dev/null)
FRONTEND_HEALTH=${FRONTEND_HEALTH:-unknown}
ADMIN_HEALTH=${ADMIN_HEALTH:-unknown}
BACKEND_HEALTH=${BACKEND_HEALTH:-unknown}

echo ""
echo "Frontend 健康状态: $FRONTEND_HEALTH"
echo "Admin   健康状态: $ADMIN_HEALTH"
echo "Backend 健康状态: $BACKEND_HEALTH"

if [ "$FRONTEND_HEALTH" = "healthy" ] && [ "$ADMIN_HEALTH" = "healthy" ] && [ "$BACKEND_HEALTH" = "healthy" ]; then
  echo ""
  echo "部署成功！"
else
  echo ""
  echo "容器已启动，部分健康检查可能需要更长时间"
fi

echo ""
echo "========== 部署完成 =========="
