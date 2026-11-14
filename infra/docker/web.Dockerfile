# React (Vite) build served by nginx; /api is proxied to the API service.
FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci || npm install
COPY apps/web/ ./
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
