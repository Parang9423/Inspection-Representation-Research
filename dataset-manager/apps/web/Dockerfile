FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

ENV NODE_TLS_REJECT_UNAUTHORIZED=0

RUN npm config set strict-ssl false \
    && npm config set registry http://registry.npmjs.org/ \
    && npm config set fetch-retries 5 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm install --no-audit --no-fund

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
