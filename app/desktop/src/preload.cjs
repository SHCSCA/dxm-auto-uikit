const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('dxmDesktop', {
  getRuntimeInfo: () => ipcRenderer.invoke('desktop:get-runtime-info'),
  loadDxmCredential: () => ipcRenderer.invoke('desktop:dxm-credential:load'),
  saveDxmCredential: (credential) => ipcRenderer.invoke('desktop:dxm-credential:save', credential),
  clearDxmCredential: () => ipcRenderer.invoke('desktop:dxm-credential:clear'),
})
