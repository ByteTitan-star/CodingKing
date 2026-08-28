const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("coderkingDesktop", {
  useRpc: true,
  openDirectory: () => ipcRenderer.invoke("dialog:openDirectory"),
  setWorkspace: (dir) => ipcRenderer.invoke("agent:setWorkspace", dir),
  prompt: (params) => ipcRenderer.invoke("agent:prompt", params),
  steer: (params) => ipcRenderer.invoke("agent:steer", params),
  followUp: (params) => ipcRenderer.invoke("agent:followUp", params),
  abort: (params) => ipcRenderer.invoke("agent:abort", params),
  getTask: (params) => ipcRenderer.invoke("agent:getTask", params),
  getDiff: (params) => ipcRenderer.invoke("agent:diff", params),
  getTree: (params) => ipcRenderer.invoke("agent:tree", params),
  readFile: (params) => ipcRenderer.invoke("agent:readFile", params),
  approve: (params) => ipcRenderer.invoke("agent:approve", params),
  reject: (params) => ipcRenderer.invoke("agent:reject", params),
  rollback: (params) => ipcRenderer.invoke("agent:rollback", params),
  accept: (params) => ipcRenderer.invoke("agent:accept", params),
  onEvent: (callback) => {
    if (typeof callback !== "function") {
      return () => undefined;
    }
    const listener = (_event, record) => callback(record);
    ipcRenderer.on("agent:event", listener);
    return () => ipcRenderer.removeListener("agent:event", listener);
  },
});
