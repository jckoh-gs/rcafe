# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# The official image renders /etc/nginx/templates/*.template with the container environment.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY docker-entrypoint.d/15-resolver.sh /docker-entrypoint.d/15-resolver.sh
COPY --from=build /app/dist /usr/share/nginx/html
# In Kubernetes use the fully qualified name: nginx's resolver does not apply search domains.
ENV BACKEND_URL=http://aicafe-backend:8000
EXPOSE 8080
