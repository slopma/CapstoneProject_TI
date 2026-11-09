# Etapa 1: Build con Node 20
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# La ruta relativa /api es atendida por el proxy de Nginx
ENV VITE_API_URL=/api
RUN npm run build

# Etapa 2: Servidor de producción ligero con Nginx
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
