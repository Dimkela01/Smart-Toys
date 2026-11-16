# Multi-arch (arm64 + amd64) web image (ARCHITECTURE.md §10).
FROM node:22-alpine

RUN corepack enable

WORKDIR /srv/web

# dependencies first, so the layer is cached independently of the source
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --prefer-offline

COPY . .

EXPOSE 3000
# compose mounts the source and a named volume over node_modules, so the dev command
# installs before starting; see infra/docker-compose.yml
CMD ["pnpm", "dev"]
