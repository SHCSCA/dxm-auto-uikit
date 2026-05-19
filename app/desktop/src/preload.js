const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('dxmDesktop', {
  platform: 'electron',
})
