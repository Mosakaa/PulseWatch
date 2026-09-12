import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const machines = [
  { name: "Awaiting agents", status: "No machines enrolled" },
];

function App() {
  return (
    <main>
      <header>
        <p className="eyebrow">Infrastructure monitoring</p>
        <h1>PulseWatch</h1>
        <span className="api-status">API connection pending</span>
      </header>
      <section aria-labelledby="machines-heading">
        <div className="section-heading">
          <h2 id="machines-heading">Machines</h2>
          <span>0 online</span>
        </div>
        <table>
          <thead><tr><th>Machine</th><th>Status</th></tr></thead>
          <tbody>
            {machines.map((machine) => (
              <tr key={machine.name}><td>{machine.name}</td><td>{machine.status}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>,
);
