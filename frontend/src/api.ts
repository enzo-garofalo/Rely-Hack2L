import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

export const api = axios.create({
  baseURL,
  // O pipeline é síncrono e pode envolver mais de um agente, mas uma
  // conexão jamais deve ficar pendurada indefinidamente na UI.
  timeout: 150_000,
});
