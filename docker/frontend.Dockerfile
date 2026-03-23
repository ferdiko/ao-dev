FROM node:18-slim AS build
WORKDIR /app
COPY src/user_interfaces/ /app/
WORKDIR /app/web_app
RUN npm install && npm run build

FROM nginx:alpine
COPY docker/frontend.nginx.conf /etc/nginx/conf.d/default.conf

# Copy built frontend
COPY --from=build /app/web_app/dist /usr/share/nginx/html

# Only expose port 80 - let host nginx handle SSL
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
