/**
 * Opero · WhatsApp Gateway (E10, enhancement)
 *
 * Ponte entre um WhatsApp REAL (whatsapp-web.js, que automatiza o WhatsApp
 * Web num Chromium headless) e a API do Opero. Duas direções, e só isso:
 *
 *   celular  --mensagem-->  este serviço  --POST /api/whatsapp/inbound-->  Django
 *   Django   --POST /send-->  este serviço  --client.sendMessage()-->  celular
 *
 * O que este serviço NÃO faz, de propósito: não acessa o banco, não conhece
 * pedido, estado, agente nem regra de negócio. Ele é transporte. Toda
 * decisão (é pedido novo? é esclarecimento? é confirmação?) é do Django, no
 * mesmo pipeline que o chat simulado usa — não existe jornada paralela.
 *
 * Regra de segurança da demo: o chat simulado é o fallback obrigatório. Se
 * o Chromium ou a sessão caírem, este processo continua de pé (só devolve
 * erro em /send) e a jornada simulada segue 100% funcional.
 *
 * Aviso: whatsapp-web.js é uma biblioteca NÃO OFICIAL que automatiza o
 * WhatsApp Web. Use um número descartável — ver README.md.
 */

const express = require("express");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

// --- configuração ---------------------------------------------------------

const PORT = Number(process.env.WHATSAPP_GATEWAY_PORT || 3001);
// Django visto de dentro da rede do compose (gateway -> Django).
const OPERO_API_URL = (process.env.OPERO_API_URL || "http://backend:8000/api").replace(/\/$/, "");
// Mesmo segredo dos dois lados: protege /send (Django -> gateway) e viaja no
// header do inbound (gateway -> Django). Nunca vai pro frontend.
const GATEWAY_TOKEN = process.env.WHATSAPP_GATEWAY_TOKEN || "";
// Volume persistente da sessão do LocalAuth: é o que evita reescanear o QR
// a cada restart do container.
const SESSION_PATH = process.env.WHATSAPP_SESSION_PATH || "/app/.wwebjs_auth";
const OPERO_TIMEOUT_MS = Number(process.env.OPERO_TIMEOUT_MS || 30000);

if (!GATEWAY_TOKEN) {
  console.error(
    "[gateway] WHATSAPP_GATEWAY_TOKEN não definido. Sem token compartilhado o " +
      "canal real fica aberto pra qualquer um — definindo no .env e subindo de novo."
  );
  process.exit(1);
}

const log = (...args) => console.log(new Date().toISOString(), "[gateway]", ...args);

// --- estado da sessão (só pra observabilidade) ----------------------------

/** waiting_qr | authenticated | connected | disconnected | starting */
let sessionStatus = "starting";
let lastQrAt = null;
let lastError = null;

function setStatus(next, detail) {
  sessionStatus = next;
  log(`sessão: ${next}${detail ? ` (${detail})` : ""}`);
}

// --- cliente WhatsApp -----------------------------------------------------

const client = new Client({
  // clientId fixo: a pasta da sessão precisa ser sempre a mesma pro
  // LocalAuth reencontrar a sessão dentro do volume.
  authStrategy: new LocalAuth({ clientId: "opero", dataPath: SESSION_PATH }),
  puppeteer: {
    headless: true,
    // A imagem base (ghcr.io/puppeteer/puppeteer) já traz o Chrome que
    // esta versão do puppeteer espera; fora do Docker, o puppeteer acha o
    // browser sozinho e esta variável fica vazia.
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      // /dev/shm do container é pequeno; sem isso o Chromium morre em
      // páginas pesadas (o WhatsApp Web é uma delas).
      "--disable-dev-shm-usage",
      "--disable-gpu",
    ],
  },
});

client.on("qr", (qr) => {
  lastQrAt = new Date().toISOString();
  setStatus("waiting_qr");
  log("escaneie o QR abaixo com o WhatsApp do número descartável:");
  qrcode.generate(qr, { small: true });
});

client.on("authenticated", () => setStatus("authenticated", "sessão salva no volume"));

client.on("auth_failure", (message) => {
  lastError = `auth_failure: ${message}`;
  setStatus("disconnected", lastError);
});

client.on("ready", () => {
  lastError = null;
  setStatus("connected");
});

client.on("disconnected", (reason) => {
  lastError = `disconnected: ${reason}`;
  setStatus("disconnected", String(reason));
  // Reinicializa sozinho: numa demo, cair e não voltar é pior do que
  // tentar de novo. O chat simulado segue como fallback enquanto isso.
  client.initialize().catch((err) => log("falha ao reinicializar:", err.message));
});

// --- entrada: celular -> Django -------------------------------------------

/** `5511999990001@c.us` -> `5511999990001` */
function phoneFromJid(jid) {
  return String(jid || "").split("@")[0].replace(/\D/g, "");
}

async function forwardToOpero(phone, text) {
  const response = await fetch(`${OPERO_API_URL}/whatsapp/inbound/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Gateway-Token": GATEWAY_TOKEN },
    body: JSON.stringify({ phone, text }),
    signal: AbortSignal.timeout(OPERO_TIMEOUT_MS),
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  return { ok: response.ok, status: response.status, payload };
}

client.on("message", async (message) => {
  try {
    // Só conversa individual: grupo (@g.us), status/broadcast e newsletter
    // não fazem parte da jornada B2B do Opero.
    if (!String(message.from).endsWith("@c.us")) return;
    if (message.isStatus) return;

    const phone = phoneFromJid(message.from);

    // Áudio existe no Opero (E9, ElevenLabs), mas por outro endpoint
    // (/api/orders/ingest-audio). Enquanto o gateway não fizer download de
    // mídia, ser explícito é melhor do que ignorar em silêncio.
    if (message.type !== "chat" || !message.body) {
      log(`mensagem de ${phone} ignorada (tipo '${message.type}')`);
      await message.reply("Por aqui eu só consigo ler mensagens de texto por enquanto.");
      return;
    }

    log(`mensagem de ${phone}: ${JSON.stringify(message.body).slice(0, 120)}`);

    const { ok, status, payload } = await forwardToOpero(phone, message.body);
    if (ok) {
      log(`Opero respondeu: pedido #${payload.orderId} · ${payload.action} · ${payload.state}`);
      // A resposta ao cliente NÃO sai daqui: quem decide o que dizer é o
      // Django, que chama /send quando tiver o texto (RF19/RF31).
      return;
    }

    log(`Opero recusou (${status}): ${JSON.stringify(payload)}`);
    if (status === 404) {
      // Telefone não cadastrado: o Django não inventa cliente (guardrail
      // #1), então o cliente precisa saber por que nada aconteceu.
      await message.reply(
        "Não encontrei o seu cadastro por este número. Fale com o seu representante."
      );
    } else {
      await message.reply("Tive um problema técnico ao registrar sua mensagem. O time já foi avisado.");
    }
  } catch (err) {
    // Erro aqui nunca pode derrubar o processo: o gateway fora do ar é
    // aceitável, mas ele morrer no meio da demo não é.
    log("falha ao processar mensagem recebida:", err.message);
    try {
      await message.reply("Não consegui falar com o sistema agora. Pode tentar de novo em instantes?");
    } catch (replyErr) {
      log("falha ao avisar o cliente:", replyErr.message);
    }
  }
});

// --- saída: Django -> celular ---------------------------------------------

const app = express();
app.use(express.json());

function authorized(req) {
  const token = req.get("X-Gateway-Token") || "";
  return token.length === GATEWAY_TOKEN.length && token === GATEWAY_TOKEN;
}

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    session: sessionStatus,
    ready: sessionStatus === "connected",
    lastQrAt,
    lastError,
  });
});

app.post("/send", async (req, res) => {
  if (!authorized(req)) {
    return res.status(401).json({ detail: "token do gateway inválido." });
  }

  const phone = String(req.body?.phone || "").replace(/\D/g, "");
  const text = String(req.body?.text || "").trim();
  if (!phone || !text) {
    return res.status(400).json({ detail: "phone e text são obrigatórios." });
  }
  if (sessionStatus !== "connected") {
    // Explícito: o Django registra a falha de entrega na mensagem em vez
    // de assumir que o cliente recebeu (guardrail #7 do CLAUDE.md).
    return res.status(503).json({ detail: `sessão do WhatsApp indisponível (${sessionStatus}).` });
  }

  try {
    // getNumberId resolve o JID de verdade do número (inclusive o nono
    // dígito do Brasil, que nem sempre existe no WhatsApp) — montar
    // `${phone}@c.us` na mão erra silenciosamente.
    const numberId = await client.getNumberId(phone);
    if (!numberId) {
      return res.status(404).json({ detail: `número ${phone} não tem WhatsApp.` });
    }
    const sent = await client.sendMessage(numberId._serialized, text);
    log(`mensagem enviada para ${phone}`);
    return res.json({ status: "sent", to: phone, messageId: sent?.id?._serialized || null });
  } catch (err) {
    log("falha ao enviar mensagem:", err.message);
    return res.status(502).json({ detail: `falha ao enviar pelo WhatsApp: ${err.message}` });
  }
});

// --- bootstrap ------------------------------------------------------------

// O HTTP sobe ANTES do Chromium: /health precisa responder mesmo enquanto a
// sessão está aguardando o QR (ou quebrada).
app.listen(PORT, () => log(`HTTP ouvindo na porta ${PORT} · Opero em ${OPERO_API_URL}`));

client.initialize().catch((err) => {
  lastError = `initialize: ${err.message}`;
  setStatus("disconnected", err.message);
});

process.on("unhandledRejection", (reason) => log("unhandledRejection:", reason));
process.on("uncaughtException", (err) => log("uncaughtException:", err.message));

const shutdown = async (signal) => {
  log(`recebido ${signal}, encerrando…`);
  try {
    await client.destroy();
  } catch (err) {
    log("falha ao encerrar o cliente:", err.message);
  }
  process.exit(0);
};
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
