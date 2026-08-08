import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";

import { api } from "./api";
import operoLogo from "./assets/opero-logo.png";
import { Icon } from "./components/Icon";
import type { IconName } from "./components/Icon";
import type {
  ApiError,
  Order,
  OrderItem,
  Timeline,
  TimelineEvent,
  ToolCall,
} from "./types";

const DEMO_CUSTOMER_ID = Number(import.meta.env.VITE_DEMO_CUSTOMER_ID || 1);
const DEMO_MESSAGE = "Quero 10 caixas de coca 2L, 6 fardos da zero e 15 caixas do óleo da última vez. Entrega amanhã de manhã.";
const ACTIVE_ORDER_KEY = "opero.activeOrderId";

const stateCopy: Record<string, { label: string; tone: "blue" | "amber" | "green" | "red" | "slate" }> = {
  received: { label: "Recebido", tone: "blue" },
  parsing: { label: "Interpretando", tone: "blue" },
  memory_loaded: { label: "Memória consultada", tone: "blue" },
  validating: { label: "Validando no ERP", tone: "blue" },
  waiting_customer: { label: "Aguardando cliente", tone: "amber" },
  ready_for_confirmation: { label: "Pronto para confirmar", tone: "green" },
  customer_confirmed: { label: "Cliente confirmou", tone: "green" },
  pending_approval: { label: "Aguardando aprovação", tone: "amber" },
  sending_to_erp: { label: "Enviando ao ERP", tone: "blue" },
  sent_to_erp: { label: "Enviado ao ERP", tone: "green" },
  erp_execution_failed: { label: "Falha no ERP", tone: "red" },
};

const agentCopy: Record<string, { label: string; icon: IconName; className: string }> = {
  intake: { label: "Order Intake Agent", icon: "message-square", className: "agent-violet" },
  order_intake: { label: "Order Intake Agent", icon: "message-square", className: "agent-violet" },
  memory: { label: "Operational Memory Agent", icon: "database", className: "agent-cyan" },
  operational_memory: { label: "Operational Memory Agent", icon: "database", className: "agent-cyan" },
  validation: { label: "Validation Agent", icon: "shield-check", className: "agent-green" },
  erp_execution: { label: "ERP Execution Agent", icon: "zap", className: "agent-blue" },
};

function getErrorMessage(error: unknown) {
  if (axios.isAxiosError<ApiError>(error)) {
    return error.response?.data.detail || error.response?.data.agentError || "Não foi possível concluir a ação.";
  }
  if (error instanceof Error) return error.message;
  return "Ocorreu um erro inesperado.";
}

function formatCurrency(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function formatDate(value?: string | null) {
  if (!value) return "A combinar";
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).format(
    new Date(`${value}T12:00:00`),
  );
}

function formatConfidence(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function StatusBadge({ state }: { state: string }) {
  const copy = stateCopy[state] || { label: state.replace(/_/g, " "), tone: "slate" as const };
  return <span className={`status-badge status-${copy.tone}`}><i />{copy.label}</span>;
}

function EmptyPanel({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return (
    <div className="empty-panel">
      <span className="empty-icon"><Icon name={icon} size={23} /></span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function Sidebar({ connected }: { connected: boolean }) {
  return (
    <aside className="sidebar">
      <div className="brand-wrap"><img src={operoLogo} alt="Opero" className="brand-logo" /></div>
      <nav className="side-nav" aria-label="Navegação principal">
        <a href="#workspace" className="nav-item active" aria-current="page" title="Operação do pedido">
          <Icon name="inbox" size={18} />
          <span>Operação do pedido</span>
          <span className="nav-pulse" />
        </a>
      </nav>
      <div className="sidebar-footer">
        <div className="operator-avatar">PD</div>
        <div className="operator-copy"><strong>Pedro</strong><span><i className={connected ? "online" : "offline"} />{connected ? "online" : "backend offline"}</span></div>
        <Icon name="chevron-down" size={16} />
      </div>
    </aside>
  );
}

function Header({
  order,
  connected,
  onReset,
  busy,
}: {
  order: Order | null;
  connected: boolean;
  onReset: () => void;
  busy: boolean;
}) {
  return (
    <header className="topbar">
      <div>
        <div className="eyebrow"><span>Opero</span><Icon name="chevron-right" size={12} /><span>Order Operations</span></div>
        <div className="title-row"><h1>Order Operations</h1>{order && <StatusBadge state={order.state} />}</div>
        <p>Converse, interprete e transforme pedidos em operações sem redigitação.</p>
      </div>
      <div className="topbar-actions">
        <span className={`health-chip ${connected ? "connected" : "disconnected"}`}><i />{connected ? "Sistema operacional" : "Backend indisponível"}</span>
        <button className="button button-ghost" type="button" onClick={onReset} disabled={busy}>
          <Icon name="rotate-ccw" size={16} /> Reset demo
        </button>
      </div>
    </header>
  );
}

interface ChatProps {
  order: Order | null;
  events: TimelineEvent[];
  onIngest: (message: string) => Promise<void>;
  onReply: (message: string) => Promise<void>;
  onIngestAudio: (audio: File) => Promise<void>;
  onListen: () => Promise<void>;
  onVoiceError: (message: string) => void;
  voiceReplyUrl: string | null;
  busy: boolean;
}

function ChatPanel({ order, events, onIngest, onReply, onIngestAudio, onListen, onVoiceError, voiceReplyUrl, busy }: ChatProps) {
  const [message, setMessage] = useState(DEMO_MESSAGE);
  const [audio, setAudio] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const messages = events.filter((event) => event.type === "message");
  const clarification = order?.currentVersion?.pendingClarification;

  useEffect(() => {
    if (!order && messages.length === 0 && !message) setMessage(DEMO_MESSAGE);
  }, [message, messages.length, order]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const clean = message.trim();
    if (!clean || busy) return;
    if (order) await onReply(clean);
    else await onIngest(clean);
    setMessage("");
  };

  const toggleRecording = async () => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      onVoiceError("Gravação não suportada neste navegador. Anexe um arquivo de áudio ou use texto.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        if (blob.size) setAudio(new File([blob], "pedido-gravado.webm", { type }));
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setRecording(false);
      };
      recorder.start();
      setRecording(true);
    } catch {
      onVoiceError("Não foi possível acessar o microfone. Libere a permissão, anexe um áudio ou use texto.");
    }
  };

  const sendAudio = async () => {
    if (!audio || busy) return;
    await onIngestAudio(audio);
    setAudio(null);
  };

  return (
    <section className="workspace-panel chat-panel" id="conversation" tabIndex={-1} aria-label="Conversa">
      <div className="panel-header">
        <div className="customer-avatar">MB</div>
        <div className="panel-title"><strong>{order?.customer.name || "Mercado Boa Compra"}</strong><span>{order ? `Conversa #${order.conversationId}` : "Canal de pedidos B2B"}</span></div>
        <span className="icon-button" aria-hidden="true"><Icon name="more-horizontal" size={19} /></span>
      </div>

      <div className="chat-scroll">
        <div className="chat-day"><span>Hoje</span></div>
        {messages.length === 0 ? (
          <div className="chat-welcome">
            <span className="chat-welcome-icon"><Icon name="message-circle" size={24} /></span>
            <strong>Conversa pronta</strong>
            <p>Envie a mensagem de demonstração para iniciar a jornada textual.</p>
          </div>
        ) : messages.map((event, index) => {
          const customer = event.sender === "customer";
          return (
            <div className={`message-row ${customer ? "customer" : "system"}`} key={`${event.at}-${index}`}>
              <div className="message-bubble">
                {event.channel === "voice" && <span className="voice-label"><Icon name="mic" size={11} /> Transcrição de áudio</span>}
                <p>{event.transcription || event.content}</p>
                <span className="message-meta">{formatTime(event.at)}{customer && <Icon name="check-check" size={13} />}</span>
              </div>
            </div>
          );
        })}

        {clarification && (
          <div className="clarification-card">
            <span><Icon name="sparkles" size={15} /></span>
            <div><small>Validation Agent pergunta</small><strong>{clarification.question}</strong></div>
          </div>
        )}

      </div>

      <div className="chat-composer-wrap">
        {order && (
          <div className="voice-response">
            <button className="listen-button" type="button" onClick={onListen} disabled={busy}><Icon name="volume-2" size={13} /> Ouvir resposta atual</button>
            {voiceReplyUrl && <div className="voice-player"><Icon name="volume-2" size={14} /><audio controls src={voiceReplyUrl}>Seu navegador não suporta áudio.</audio></div>}
          </div>
        )}
        {audio && (
          <div className="audio-ready">
            <span><Icon name="mic" size={13} /><strong>{audio.name}</strong><small>{Math.max(1, Math.round(audio.size / 1024))} KB pronto para transcrever</small></span>
            <button type="button" aria-label="Remover áudio" onClick={() => setAudio(null)} disabled={busy}><Icon name="x" size={14} /></button>
            <button className="button button-primary" type="button" onClick={sendAudio} disabled={busy}>Enviar áudio</button>
          </div>
        )}
        <form className="chat-composer" onSubmit={send}>
          {!order && (
            <>
              <button className={`composer-icon ${recording ? "recording" : ""}`} type="button" onClick={toggleRecording} disabled={busy} aria-label={recording ? "Parar gravação" : "Gravar pedido em áudio"} title={recording ? "Parar gravação" : "Gravar áudio"}><Icon name={recording ? "square" : "mic"} size={16} /></button>
              <label className="composer-icon" title="Anexar áudio">
                <Icon name="link" size={16} />
                <input className="audio-input" type="file" accept="audio/*" aria-label="Anexar arquivo de áudio" disabled={busy} onChange={(event) => setAudio(event.target.files?.[0] || null)} />
              </label>
            </>
          )}
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder={order ? "Responder ao cliente..." : "Digite o pedido..."}
            rows={1}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button className="send-button" type="submit" disabled={busy || !message.trim()} title="Enviar mensagem" aria-label="Enviar mensagem"><Icon name="send" size={17} /></button>
        </form>
        <small>Enter para enviar • Shift + Enter para nova linha</small>
      </div>
    </section>
  );
}

function ItemCard({ item, index }: { item: OrderItem; index: number }) {
  const ambiguous = item.status === "ambiguous";
  return (
    <article className={`order-item ${ambiguous ? "item-ambiguous" : ""}`}>
      <div className="item-index">{String(index + 1).padStart(2, "0")}</div>
      <div className="item-main">
        <div className="item-title-row">
          <div><strong>{item.productGuess || item.rawText || "Item do pedido"}</strong><span>{item.sku || "SKU aguardando validação"}</span></div>
          <div className="item-chips">
            <span className={`confidence-chip ${ambiguous ? "low" : "high"}`}>Confiança {formatConfidence(item.confidence)}</span>
            <span className={`validation-chip ${ambiguous ? "pending" : "validated"}`}><Icon name={ambiguous ? "help-circle" : "check"} size={12} />{ambiguous ? "Ambíguo" : "Validado"}</span>
          </div>
        </div>
        <p className="evidence"><Icon name="quote" size={12} /> “{item.rawText}”</p>
        <div className="item-metrics">
          <div><span>Quantidade</span><strong>{item.quantity ?? "—"} {item.unit}</strong></div>
          <div><span>Unidade ERP</span><strong>{item.catalogUnit || "—"}</strong></div>
          <div><span>Preço unit.</span><strong>{formatCurrency(item.unitPrice)}</strong></div>
          <div><span>Subtotal</span><strong>{formatCurrency(item.subtotal)}</strong></div>
          <div><span>Estoque</span><strong className={item.inStock === false ? "stock-no" : "stock-ok"}>{item.inStock === undefined ? "—" : item.inStock ? "Disponível" : "Indisponível"}</strong></div>
        </div>
      </div>
    </article>
  );
}

function OrderPanel({ order, busy, onConfirm, onApprove }: { order: Order | null; busy: boolean; onConfirm: () => void; onApprove: () => void }) {
  const version = order?.currentVersion;
  const canConfirm = order?.state === "ready_for_confirmation";
  const canApprove = order?.state === "pending_approval";

  return (
    <section className="workspace-panel order-panel" id="structured-order" tabIndex={-1} aria-label="Pedido estruturado">
      <div className="panel-header order-header">
        <div className="panel-title"><span>Pedido estruturado</span><strong>{order ? `PED-${String(order.id).padStart(5, "0")}` : "Novo pedido"}</strong></div>
        {order && <span className="version-chip">v{version?.versionNumber || 1}</span>}
      </div>

      {!order || !version ? (
        <EmptyPanel icon="package" title="Nenhum pedido selecionado" text="A estrutura validada aparecerá aqui assim que a conversa começar." />
      ) : (
        <div className="order-content">
          <div className="order-overview">
            <div><span>Cliente</span><strong>{order.customer.name}</strong><small>{order.customer.phone}</small></div>
            <div><span>Entrega</span><strong>{formatDate(version.deliveryDate)}</strong><small>janela preferencial: manhã</small></div>
            <div><span>Status</span><StatusBadge state={order.state} /><small>atualizado {formatTime(order.updatedAt)}</small></div>
          </div>

          <div className="section-heading"><div><span>Itens do pedido</span><small>{version.items.length} {version.items.length === 1 ? "item" : "itens"}</small></div><span className="erp-source"><Icon name="link" size={13} /> Dados validados no ERP</span></div>
          <div className="items-list">
            {version.items.length ? version.items.map((item, index) => <ItemCard item={item} index={index} key={item.itemRef} />) : <div className="inline-empty">Os agentes ainda estão interpretando os itens.</div>}
          </div>

          {version.pendingClarification && (
            <div className="pending-block"><Icon name="alert-circle" size={18} /><div><strong>Esclarecimento necessário</strong><p>{version.pendingClarification.question}</p></div></div>
          )}

          <div className="order-summary">
            <div className="summary-copy"><span>Total do pedido</span><strong>{formatCurrency(version.total)}</strong><small>Calculado deterministicamente • sem impostos adicionais</small></div>
            <div className="approval-flow">
              <div className={version.customerConfirmed ? "flow-step done" : "flow-step"}><span>{version.customerConfirmed ? <Icon name="check" size={13} /> : "1"}</span><div><strong>Cliente</strong><small>{version.customerConfirmed ? "Confirmado" : "Aguardando"}</small></div></div>
              <span className="flow-line" />
              <div className={version.operatorApproved ? "flow-step done" : "flow-step"}><span>{version.operatorApproved ? <Icon name="check" size={13} /> : "2"}</span><div><strong>Operador</strong><small>{version.operatorApproved ? "Aprovado" : "Revisão humana"}</small></div></div>
              <span className="flow-line" />
              <div className={order.state === "sent_to_erp" ? "flow-step done" : "flow-step"}><span>{order.state === "sent_to_erp" ? <Icon name="check" size={13} /> : "3"}</span><div><strong>ERP</strong><small>{order.state === "sent_to_erp" ? "Criado" : "Pendente"}</small></div></div>
            </div>
          </div>

          <div className="order-actions">
            {canConfirm && <button className="button button-secondary" type="button" onClick={onConfirm} disabled={busy}><Icon name="check-circle" size={17} /> Confirmar como cliente</button>}
            {canApprove && <button className="button button-primary" type="button" onClick={onApprove} disabled={busy}><Icon name="shield-check" size={17} /> Aprovar e enviar ao ERP</button>}
            {order.state === "waiting_customer" && <span className="action-hint"><Icon name="clock" size={15} /> Responda ao esclarecimento no chat</span>}
            {order.state === "sent_to_erp" && <span className="success-hint"><Icon name="check-circle" size={16} /> Pedido concluído com sucesso</span>}
          </div>
        </div>
      )}
    </section>
  );
}

function ToolCallRow({ call }: { call: ToolCall }) {
  return (
    <details className="tool-call">
      <summary><span className={call.success ? "tool-status ok" : "tool-status fail"}><Icon name={call.success ? "check" : "x"} size={10} /></span><code>{call.tool}</code><Icon name="chevron-down" size={13} /></summary>
      <div className="tool-details"><span>entrada</span><pre>{JSON.stringify(call.input, null, 2)}</pre><span>saída</span><pre>{JSON.stringify(call.output, null, 2)}</pre></div>
    </details>
  );
}

function TimelineCard({ event }: { event: TimelineEvent }) {
  if (event.type === "agent_run") {
    const copy = agentCopy[event.agent || ""] || { label: event.agent || "Agente", icon: "sparkles" as IconName, className: "agent-blue" };
    return (
      <article className={`timeline-card ${copy.className}`}>
        <span className="timeline-dot"><Icon name={copy.icon} size={14} /></span>
        <div className="timeline-card-body">
          <div className="timeline-card-head"><div><strong>{copy.label}</strong><span>{event.success ? "concluído" : "falhou"}</span></div><time>{formatTime(event.at)}</time></div>
          <p>{event.reason || "Execução registrada no fluxo do pedido."}</p>
          {event.previousState && event.nextState && <div className="transition-pill"><span>{stateCopy[event.previousState]?.label || event.previousState}</span><Icon name="arrow-right" size={12} /><strong>{stateCopy[event.nextState]?.label || event.nextState}</strong></div>}
          {!!event.toolCalls?.length && <div className="tool-list">{event.toolCalls.map((call, index) => <ToolCallRow call={call} key={`${call.tool}-${index}`} />)}</div>}
        </div>
      </article>
    );
  }

  if (event.type === "state_transition") {
    return (
      <div className="timeline-mini"><span className="mini-icon"><Icon name="git-commit" size={13} /></span><div><strong>Estado atualizado</strong><p>{stateCopy[event.from || ""]?.label || event.from} <Icon name="arrow-right" size={11} /> {stateCopy[event.to || ""]?.label || event.to}</p></div><time>{formatTime(event.at)}</time></div>
    );
  }

  if (event.type === "customer_confirmation" || event.type === "operator_approval") {
    const approval = event.type === "operator_approval";
    return (
      <div className="timeline-mini important"><span className="mini-icon"><Icon name={approval ? "shield-check" : "check-circle"} size={13} /></span><div><strong>{approval ? "Aprovação humana" : "Confirmação do cliente"}</strong><p>{approval ? event.approvedBy || "Operador" : `Versão ${event.versionNumber}`} confirmou a operação</p></div><time>{formatTime(event.at)}</time></div>
    );
  }

  return (
    <div className="timeline-mini muted"><span className="mini-icon"><Icon name="message-circle" size={13} /></span><div><strong>Mensagem recebida</strong><p>{event.sender === "customer" ? "Cliente" : "Opero"} • {event.channel || "texto"}</p></div><time>{formatTime(event.at)}</time></div>
  );
}

function TimelinePanel({ timeline }: { timeline: Timeline | null }) {
  const events = useMemo(() => timeline?.events || [], [timeline]);
  const agentRuns = events.filter((event) => event.type === "agent_run").length;
  const tools = events.reduce((sum, event) => sum + (event.toolCalls?.length || 0), 0);
  const memoryProposals = events.flatMap((event) =>
    (event.toolCalls || [])
      .filter((call) => call.tool === "create_memory_proposal" && call.success)
      .map((call) => {
        const input = asRecord(call.input);
        const output = asRecord(call.output);
        return {
          alias: typeof input?.alias === "string" ? input.alias : "Novo alias",
          sku: typeof input?.sku === "string" ? input.sku : "SKU não informado",
          status: typeof output?.status === "string" ? output.status : "pending_review",
        };
      }),
  );
  return (
    <section className="workspace-panel timeline-panel" id="agent-timeline" tabIndex={-1} aria-label="Agentes e logs">
      <div className="panel-header">
        <div className="panel-title"><span>Auditoria em tempo real</span><strong>Runs &amp; Logs</strong></div>
        <span className="live-chip"><i /> AUDITÁVEL</span>
      </div>
      {!timeline ? (
        <EmptyPanel icon="activity" title="Timeline aguardando" text="Cada agente, transição e tool call ficará visível aqui." />
      ) : (
        <>
          <div className="timeline-stats"><div><strong>{agentRuns}</strong><span>agentes</span></div><div><strong>{tools}</strong><span>tool calls</span></div><div><strong>{events.length}</strong><span>eventos</span></div></div>
          {memoryProposals.map((proposal, index) => (
            <div className="memory-proposal" key={`${proposal.alias}-${proposal.sku}-${index}`}>
              <span><Icon name="database" size={15} /></span>
              <div><small>Proposta de memória · {proposal.status}</small><strong>“{proposal.alias}” → {proposal.sku}</strong><p>Aguardando revisão humana; não virou memória confiável automaticamente.</p></div>
            </div>
          ))}
          <div className="timeline-scroll"><div className="timeline-line" />{events.map((event, index) => <TimelineCard event={event} key={`${event.type}-${event.at}-${index}`} />)}</div>
        </>
      )}
    </section>
  );
}

function ReceiptModal({ order, onClose }: { order: Order; onClose: () => void }) {
  const receipt = order.currentVersion?.erpReceipt;
  if (!receipt) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="receipt-modal" role="dialog" aria-modal="true" aria-labelledby="receipt-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} type="button" aria-label="Fechar recibo"><Icon name="x" size={19} /></button>
        <span className="receipt-success"><Icon name="check" size={26} /></span>
        <p className="receipt-kicker">Operação concluída</p>
        <h2 id="receipt-title">Pedido criado no ERP</h2>
        <p>O pedido foi validado, aprovado e enviado uma única vez com proteção de idempotência.</p>
        <div className="receipt-number"><span>Número externo</span><strong>{receipt.erpOrderId}</strong></div>
        <div className="receipt-grid"><div><span>Status</span><strong><i /> {receipt.status}</strong></div><div><span>Versão</span><strong>v{order.currentVersion?.versionNumber}</strong></div></div>
        <div className="idempotency"><span>Idempotency-Key</span><code>{receipt.idempotencyKey}</code></div>
        <details className="receipt-payload"><summary>Payload enviado ao ERP</summary><pre>{JSON.stringify(receipt.payload, null, 2)}</pre></details>
        <button className="button button-primary button-full" type="button" onClick={onClose}>Voltar ao pedido</button>
      </div>
    </div>
  );
}

function App() {
  const [health, setHealth] = useState<"loading" | "ok" | "error">("loading");
  const [order, setOrder] = useState<Order | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReceipt, setShowReceipt] = useState(false);
  const [voiceReplyUrl, setVoiceReplyUrl] = useState<string | null>(null);

  useEffect(() => {
    api.get("/health/").then(() => setHealth("ok")).catch(() => setHealth("error"));
  }, []);

  useEffect(() => () => {
    if (voiceReplyUrl) URL.revokeObjectURL(voiceReplyUrl);
  }, [voiceReplyUrl]);

  const loadOrder = useCallback(async (id: number) => {
    const [orderResponse, timelineResponse] = await Promise.all([
      api.get<Order>(`/orders/${id}/`),
      api.get<Timeline>(`/orders/${id}/timeline/`),
    ]);
    setOrder(orderResponse.data);
    setTimeline(timelineResponse.data);
    localStorage.setItem(ACTIVE_ORDER_KEY, String(id));
    return orderResponse.data;
  }, []);

  useEffect(() => {
    const savedOrderId = Number(localStorage.getItem(ACTIVE_ORDER_KEY));
    if (!Number.isInteger(savedOrderId) || savedOrderId <= 0) return;
    loadOrder(savedOrderId).catch(() => {
      localStorage.removeItem(ACTIVE_ORDER_KEY);
      setError("O pedido anterior não está mais disponível. Inicie uma nova jornada.");
    });
  }, [loadOrder]);

  const loadPipelineOrderFromError = async (actionError: unknown, fallbackId?: number) => {
    const errorOrderId = axios.isAxiosError<ApiError>(actionError) ? actionError.response?.data.orderId : undefined;
    const id = errorOrderId || fallbackId;
    if (id) await loadOrder(id);
    throw actionError;
  };

  const runAction = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setBusy(false);
    }
  };

  const ingest = (message: string) => runAction(async () => {
    try {
      const response = await api.post<{ orderId: number }>("/orders/ingest/", { customerId: DEMO_CUSTOMER_ID, message });
      await loadOrder(response.data.orderId);
    } catch (actionError) {
      await loadPipelineOrderFromError(actionError);
    }
  });

  const ingestAudio = (audio: File) => runAction(async () => {
    const body = new FormData();
    body.append("customerId", String(DEMO_CUSTOMER_ID));
    body.append("audio", audio);
    try {
      const response = await api.post<{ orderId: number }>("/orders/ingest-audio/", body);
      await loadOrder(response.data.orderId);
    } catch (actionError) {
      await loadPipelineOrderFromError(actionError);
    }
  });

  const reply = (message: string) => runAction(async () => {
    if (!order) return;
    try {
      await api.post(`/orders/${order.id}/customer-reply/`, { message, itemRef: order.currentVersion?.pendingClarification?.itemRef });
      await loadOrder(order.id);
    } catch (actionError) {
      await loadPipelineOrderFromError(actionError, order.id);
    }
  });

  const confirm = () => runAction(async () => {
    if (!order) return;
    await api.post(`/orders/${order.id}/confirm/`);
    await loadOrder(order.id);
  });

  const approve = () => runAction(async () => {
    if (!order) return;
    try {
      await api.post(`/orders/${order.id}/approve/`, { approvedBy: "Pedro · Operador", notes: "Revisado no console Opero" });
      const updated = await loadOrder(order.id);
      if (updated.currentVersion?.erpReceipt) setShowReceipt(true);
    } catch (actionError) {
      await loadPipelineOrderFromError(actionError, order.id);
    }
  });

  const listen = () => runAction(async () => {
    if (!order) return;
    const response = await api.get<Blob>(`/orders/${order.id}/voice-reply/`, { responseType: "blob" });
    if (!response.data.type.startsWith("audio/")) {
      const payload = JSON.parse(await response.data.text()) as ApiError & { audioAvailable?: boolean };
      throw new Error(payload.voiceError || "A resposta em áudio está indisponível. O fluxo por texto continua funcionando.");
    }
    setVoiceReplyUrl((previous) => {
      if (previous) URL.revokeObjectURL(previous);
      return URL.createObjectURL(response.data);
    });
  });

  const reset = () => runAction(async () => {
    await api.post("/demo/reset/");
    setOrder(null);
    setTimeline(null);
    setShowReceipt(false);
    setVoiceReplyUrl(null);
    localStorage.removeItem(ACTIVE_ORDER_KEY);
  });

  const messageEvents = timeline?.events || [];

  return (
    <div className="app-shell">
      <Sidebar connected={health === "ok"} />
      <main className="main-shell">
        <Header order={order} connected={health === "ok"} onReset={reset} busy={busy} />
        {error && <div className="error-toast" role="alert"><Icon name="alert-circle" size={17} /><span>{error}</span><button type="button" aria-label="Fechar erro" onClick={() => setError(null)}><Icon name="x" size={16} /></button></div>}
        {busy && <div className="progress-bar" role="progressbar" aria-label="Processando ação"><span /></div>}
        <div className="workspace-grid" id="workspace">
          <ChatPanel order={order} events={messageEvents} onIngest={ingest} onReply={reply} onIngestAudio={ingestAudio} onListen={listen} onVoiceError={setError} voiceReplyUrl={voiceReplyUrl} busy={busy} />
          <OrderPanel order={order} busy={busy} onConfirm={confirm} onApprove={approve} />
          <TimelinePanel timeline={timeline} />
        </div>
      </main>
      {showReceipt && order && <ReceiptModal order={order} onClose={() => setShowReceipt(false)} />}
    </div>
  );
}

export default App;
