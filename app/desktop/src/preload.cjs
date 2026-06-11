const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('dxmDesktop', {
  getRuntimeInfo: () => ipcRenderer.invoke('desktop:get-runtime-info'),
})
