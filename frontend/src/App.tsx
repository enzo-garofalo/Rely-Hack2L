import { useEffect, useState } from "react";

import { api } from "./api";

type HealthStatus = "loading" | "ok" | "erro";

function App() {
  const [status, setStatus] = useState<HealthStatus>("loading");

  useEffect(() => {
    api
      .get("/health/")
      .then((res) => setStatus(res.data.status === "ok" ? "ok" : "erro"))
      .catch(() => setStatus("erro"));
  }, []);

  const badge: Record<HealthStatus, string> = {
    loading: "bg-gray-200 text-gray-700",
    ok: "bg-green-100 text-green-800",
    erro: "bg-red-100 text-red-800",
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="text-center space-y-4">
        <h1 className="text-3xl font-semibold text-slate-800">Opero</h1>
        <p className="text-slate-500">console de pedidos B2B</p>
        <span className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${badge[status]}`}>
          backend: {status}
        </span>
      </div>
    </div>
  );
}

export default App;
