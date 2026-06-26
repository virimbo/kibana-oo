// OO-GX type system — self-hosted (Vite-bundled), works without internet/VPN.
import "@fontsource/chakra-petch/500.css";
import "@fontsource/chakra-petch/600.css";
import "@fontsource/chakra-petch/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return React.createElement(
        "div",
        {
          style: {
            padding: "40px",
            color: "#f85149",
            background: "#0d1117",
            height: "100vh",
            fontFamily: "monospace",
          },
        },
        React.createElement("h2", null, "Something went wrong"),
        React.createElement("pre", null, this.state.error.message),
        React.createElement(
          "button",
          {
            onClick: () => {
              sessionStorage.clear();
              window.location.reload();
            },
            style: {
              marginTop: "20px",
              padding: "10px 20px",
              background: "#58a6ff",
              color: "#fff",
              border: "none",
              borderRadius: "8px",
              cursor: "pointer",
            },
          },
          "Reload"
        )
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
