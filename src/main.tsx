import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { FilmLabProvider } from "./store/filmLab";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <FilmLabProvider>
      <App />
    </FilmLabProvider>
  </React.StrictMode>,
);
