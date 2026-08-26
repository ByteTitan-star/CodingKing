const { contextBridge, ipcRenderer } = require("electron");

const API_BASE = process.env.CODERKING_API_BASE || "http://127.0.0.1:8000";

contextBridge.exposeInMainWorld("coderkingDesktop", {
  openDirectory: () => ipcRenderer.invoke("dialog:openDirectory"),
  isDesktop: true,
  apiBase: API_BASE,
});
