import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import { PrototypeProvider } from "./state/PrototypeContext.jsx";
import { BatchPrototypeProvider } from "./state/BatchPrototypeContext.jsx";
import "./styles.css";
import "./complete.css";
import "./batch.css";
import "./production-redesign.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <PrototypeProvider>
      <BatchPrototypeProvider>
        <App />
      </BatchPrototypeProvider>
    </PrototypeProvider>
  </React.StrictMode>,
);
