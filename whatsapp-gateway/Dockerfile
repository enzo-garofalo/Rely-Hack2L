# Imagem oficial do Puppeteer: já vem com o Chrome e TODAS as libs de
# sistema que ele precisa (libnss3, libatk, libgbm, fontes…). Instalar isso
# na mão sobre um node:slim é a receita clássica de "a sessão não sobe".
#
# A tag é a MESMA versão de puppeteer que o whatsapp-web.js 1.34.7 declara
# como dependência (puppeteer 24.38.0) — browser e biblioteca casados de
# propósito. Ao subir a versão do whatsapp-web.js, confira
# `npm view whatsapp-web.js dependencies` e mova esta tag junto.
FROM ghcr.io/puppeteer/puppeteer:24.38.0

# O postinstall do puppeteer tentaria baixar outro Chrome; o da imagem já
# serve. PUPPETEER_EXECUTABLE_PATH continua vindo da imagem base.
ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    NODE_ENV=production

USER root
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY index.js ./

# A sessão do LocalAuth vive aqui e é montada como volume no compose. O
# diretório precisa existir na imagem E pertencer ao pptruser: um volume
# nomeado herda o dono do caminho da imagem: sem isso, o volume nasce do
# root e o processo não consegue gravar a sessão (QR novo a cada restart).
RUN mkdir -p /app/.wwebjs_auth /app/.wwebjs_cache && chown -R pptruser:pptruser /app

USER pptruser

EXPOSE 3001

CMD ["node", "index.js"]
