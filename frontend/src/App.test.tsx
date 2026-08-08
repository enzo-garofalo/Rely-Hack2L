import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { api } from "./api";
import type { Order, OrderItem, Timeline } from "./types";

vi.mock("./api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

const now = "2026-08-08T18:00:00Z";

const cocaItem: OrderItem = {
  itemRef: "item-1",
  rawText: "10 caixas de coca 2L",
  productGuess: "coca 2L",
  quantity: 10,
  unit: "caixas",
  status: "resolved",
  sku: "COCA-2L-CX6",
  catalogUnit: "caixa com 6",
  unitPrice: 54,
  subtotal: 540,
  inStock: true,
  confidence: 0.98,
};

const zeroAmbiguous: OrderItem = {
  itemRef: "item-2",
  rawText: "6 fardos da zero",
  productGuess: "zero",
  quantity: 6,
  unit: "fardos",
  status: "ambiguous",
  confidence: 0.61,
  ambiguities: [{ field: "sku", question: "Você quis dizer Coca-Cola Zero lata, fardo com 12?", candidates: ["COCA-ZERO-LATA-CX12"] }],
};

function makeOrder(state: string, overrides: Partial<Order["currentVersion"]> = {}): Order {
  const ready = ["ready_for_confirmation", "pending_approval", "sent_to_erp"].includes(state);
  const zeroResolved: OrderItem = {
    ...zeroAmbiguous,
    status: "resolved",
    sku: "COCA-ZERO-LATA-CX12",
    catalogUnit: "fardo com 12",
    unitPrice: 42,
    subtotal: 252,
    inStock: true,
    confidence: 0.96,
  };
  return {
    id: 7,
    state,
    conversationId: 12,
    customer: { id: 1, name: "Mercado Boa Compra", phone: "5511999990001" },
    createdAt: now,
    updatedAt: now,
    currentVersion: {
      versionNumber: ready ? 2 : 1,
      status: ready ? "validated" : "needs_clarification",
      deliveryDate: "2026-08-09",
      missingFields: [],
      evidence: ["10 caixas de coca 2L"],
      total: ready ? 792 : 540,
      items: [cocaItem, ready ? zeroResolved : zeroAmbiguous],
      pendingClarification: ready ? null : {
        itemRef: "item-2",
        field: "sku",
        question: "Você quis dizer Coca-Cola Zero lata, fardo com 12?",
        candidates: ["COCA-ZERO-LATA-CX12"],
      },
      customerConfirmed: state === "pending_approval" || state === "sent_to_erp",
      operatorApproved: state === "sent_to_erp",
      erpReceipt: state === "sent_to_erp" ? {
        erpOrderId: "ERP-2026-0001",
        status: "created",
        idempotencyKey: "opero-order-7-v2",
        payload: { customerId: 1, items: [{ sku: "COCA-2L-CX6", qty: 10 }], total: 792 },
      } : null,
      ...overrides,
    },
  };
}

function makeTimeline(withProposal = false): Timeline {
  return {
    orderId: 7,
    events: [
      { type: "message", at: now, sender: "customer", channel: "text", content: "Pedido de demonstração" },
      {
        type: "agent_run",
        at: now,
        agent: "validation",
        previousState: "validating",
        nextState: withProposal ? "ready_for_confirmation" : "waiting_customer",
        success: true,
        reason: "Catálogo, preço e estoque validados.",
        toolCalls: [
          { tool: "check_inventory", input: { sku: "COCA-2L-CX6" }, output: { available: 80 }, success: true, at: now },
          ...(withProposal ? [{
            tool: "create_memory_proposal",
            input: { alias: "fardo da zero", sku: "COCA-ZERO-LATA-CX12" },
            output: { proposalId: 1, status: "pending_review" },
            success: true,
            at: now,
          }] : []),
        ],
      },
    ],
  };
}

function installHappyApi() {
  let currentOrder = makeOrder("waiting_customer");
  let timeline = makeTimeline();

  vi.mocked(api.get).mockImplementation(async (url) => {
    if (url === "/health/") return { data: { status: "ok" } } as never;
    if (String(url).endsWith("/timeline/")) return { data: timeline } as never;
    return { data: currentOrder } as never;
  });
  vi.mocked(api.post).mockImplementation(async (url, payload) => {
    if (url === "/orders/ingest/") return { data: { orderId: 7 } } as never;
    if (url === "/orders/ingest-audio/") return { data: { orderId: 7, transcription: "Pedido de demonstração" } } as never;
    if (String(url).endsWith("/customer-reply/")) {
      expect(payload).toEqual({ message: "Sim, a lata 350ml em fardo com 12.", itemRef: "item-2" });
      currentOrder = makeOrder("ready_for_confirmation");
      timeline = makeTimeline(true);
      return { data: { orderId: 7 } } as never;
    }
    if (String(url).endsWith("/confirm/")) {
      currentOrder = makeOrder("pending_approval");
      return { data: { orderId: 7 } } as never;
    }
    if (String(url).endsWith("/approve/")) {
      currentOrder = makeOrder("sent_to_erp");
      return { data: { orderId: 7 } } as never;
    }
    if (url === "/demo/reset/") return { data: { status: "reset" } } as never;
    throw new Error(`POST inesperado: ${String(url)}`);
  });
}

async function ingestDemo(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Enviar mensagem" }));
  await screen.findByText("COCA-2L-CX6");
}

describe("console Opero", () => {
  beforeEach(() => {
    installHappyApi();
  });

  it("mostra health check e os três painéis no estado vazio", async () => {
    render(<App />);

    expect(await screen.findByText("Sistema operacional")).toBeInTheDocument();
    expect(screen.getByText("Conversa pronta")).toBeInTheDocument();
    expect(screen.getByText("Nenhum pedido selecionado")).toBeInTheDocument();
    expect(screen.getByText("Timeline aguardando")).toBeInTheDocument();
  });

  it("recupera o pedido ativo após recarregar a página", async () => {
    localStorage.setItem("opero.activeOrderId", "7");
    render(<App />);

    expect(await screen.findByText("COCA-2L-CX6")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/orders/7/");
    expect(api.get).toHaveBeenCalledWith("/orders/7/timeline/");
  });

  it("envia o contrato correto e apresenta ambiguidade, confiança, estoque e auditoria", async () => {
    const user = userEvent.setup();
    render(<App />);

    await ingestDemo(user);

    expect(api.post).toHaveBeenCalledWith("/orders/ingest/", expect.objectContaining({ customerId: 1, message: expect.stringContaining("10 caixas") }));
    expect(screen.getByText("Confiança 98%")).toBeInTheDocument();
    expect(screen.getByText("Disponível")).toBeInTheDocument();
    expect(screen.getAllByText("Ambíguo").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Você quis dizer Coca-Cola Zero lata, fardo com 12?")).toHaveLength(2);
    expect(screen.getByText("Validation Agent")).toBeInTheDocument();
    expect(screen.getByText("check_inventory")).toBeInTheDocument();
  });

  it("percorre resposta, confirmação, aprovação, recibo idempotente e reset", async () => {
    const user = userEvent.setup();
    render(<App />);
    await ingestDemo(user);

    const composer = screen.getByPlaceholderText("Responder ao cliente...");
    await user.clear(composer);
    await user.type(composer, "Sim, a lata 350ml em fardo com 12.");
    await user.click(screen.getByRole("button", { name: "Enviar mensagem" }));

    expect(await screen.findByText(/“fardo da zero”/)).toBeInTheDocument();
    expect(screen.getByText(/Aguardando revisão humana/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmar como cliente" }));
    await user.click(await screen.findByRole("button", { name: "Aprovar e enviar ao ERP" }));

    expect(await screen.findByRole("dialog", { name: "Pedido criado no ERP" })).toBeInTheDocument();
    expect(screen.getByText("ERP-2026-0001")).toBeInTheDocument();
    expect(screen.getByText("opero-order-7-v2")).toBeInTheDocument();
    await user.click(screen.getByText("Payload enviado ao ERP"));
    expect(screen.getByText(/COCA-2L-CX6/, { selector: ".receipt-payload pre" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Voltar ao pedido" }));
    await user.click(screen.getByRole("button", { name: "Reset demo" }));

    expect(await screen.findByText("Conversa pronta")).toBeInTheDocument();
    expect(screen.getByText("Nenhum pedido selecionado")).toBeInTheDocument();
  });

  it("expõe erro recuperável sem transformar falha em sucesso", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error("modelo indisponível"));
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Enviar mensagem" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("modelo indisponível");
    expect(screen.queryByText("COCA-2L-CX6")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar mensagem" })).toBeEnabled();
  });

  it("bloqueia envio concorrente enquanto a primeira mutação está pendente", async () => {
    let resolveIngest: ((value: unknown) => void) | undefined;
    vi.mocked(api.post).mockImplementationOnce(() => new Promise((resolve) => { resolveIngest = resolve; }) as never);
    const user = userEvent.setup();
    render(<App />);

    const send = screen.getByRole("button", { name: "Enviar mensagem" });
    await user.click(send);
    expect(send).toBeDisabled();
    await user.click(send);
    expect(api.post).toHaveBeenCalledTimes(1);

    resolveIngest?.({ data: { orderId: 7 } });
    await waitFor(() => expect(screen.getByText("COCA-2L-CX6")).toBeInTheDocument());
  });

  it("tolera campos opcionais e valores nulos do backend", async () => {
    const sparse = makeOrder("ready_for_confirmation", {
      deliveryDate: null,
      total: null,
      evidence: [],
      items: [{ ...cocaItem, unitPrice: null, subtotal: null, inStock: undefined, confidence: null }],
    });
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === "/health/") return { data: { status: "ok" } } as never;
      if (String(url).endsWith("/timeline/")) return { data: makeTimeline() } as never;
      return { data: sparse } as never;
    });
    const user = userEvent.setup();
    render(<App />);

    await ingestDemo(user);

    expect(screen.getByText("A combinar")).toBeInTheDocument();
    expect(screen.getByText("Confiança —")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("anexa e envia áudio no contrato multipart do mesmo fluxo de pedido", async () => {
    const user = userEvent.setup();
    render(<App />);
    const file = new File(["audio-demo"], "pedido.webm", { type: "audio/webm" });

    await user.upload(screen.getByLabelText("Anexar arquivo de áudio"), file);
    expect(screen.getByText("pedido.webm")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Enviar áudio" }));

    await screen.findByText("COCA-2L-CX6");
    const call = vi.mocked(api.post).mock.calls.find(([url]) => url === "/orders/ingest-audio/");
    expect(call).toBeDefined();
    const body = call?.[1] as FormData;
    expect(body.get("customerId")).toBe("1");
    expect(body.get("audio")).toBe(file);
  });

  it("oferece fallback textual quando o navegador não suporta gravação", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Gravar pedido em áudio" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Anexe um arquivo de áudio ou use texto");
    expect(screen.getByPlaceholderText("Digite o pedido...")).toBeEnabled();
  });
});
