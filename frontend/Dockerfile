# Build estático. `npm run dev` não vai pra produção: o dev server do Vite
# é single-process e não faz o bundle. O docker-compose local sobrescreve o
# CMD com `npm run dev`, então o fluxo de desenvolvimento não muda.
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# As variáveis VITE_* são inlined no bundle no momento do build — não são
# lidas em runtime. Por isso entram como ARG: no Railway é preciso declará-las
# como variáveis do serviço (o builder as repassa como build args).
ARG VITE_API_BASE_URL
ARG VITE_DEMO_CUSTOMER_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_DEMO_CUSTOMER_ID=$VITE_DEMO_CUSTOMER_ID

RUN npm run build

FROM node:20-alpine AS runtime

WORKDIR /app

RUN npm install -g serve@14.2.3

COPY --from=build /app/dist ./dist

EXPOSE 5173

# -s: fallback pro index.html, senão qualquer rota que não a raiz dá 404.
# Forma shell porque $PORT é injetado pela plataforma em runtime.
CMD ["sh", "-c", "serve -s dist -l ${PORT:-5173}"]
