import { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Machine = { id: string; name: string; hostname: string; status: "pending" | "online" | "degraded" | "offline"; last_heartbeat_at: string | null };
type Alert = { id: number; machine_id: string; machine_name: string; kind: string; state: string; severity: string; message: string; created_at: string };
type Telemetry = { collected_at: string; cpu_percent: number; memory_percent: number; disk_percent: number };
type AlertRule = { id: number; machine_id: string; metric: string; threshold: number; severity: "info" | "warning" | "critical"; enabled: boolean };

async function request<T>(path: string, token?: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(body.detail ?? "Request failed");
  }
  return response.json() as Promise<T>;
}

function LineChart({ data, metric, color }: { data: Telemetry[]; metric: "cpu_percent" | "memory_percent" | "disk_percent"; color: string }) {
  const points = useMemo(() => data.length < 2 ? "" : data.map((sample, index) => `${(index / (data.length - 1)) * 100},${100 - sample[metric]}`).join(" "), [data, metric]);
  return <div className="chart" aria-label={`${metric} history`}><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"><path d="M0 25H100 M0 50H100 M0 75H100" className="chart-grid" />{points && <polyline points={points} fill="none" stroke={color} strokeWidth="2.5" vectorEffect="non-scaling-stroke" />}</svg>{!points && <span className="chart-empty">Waiting for telemetry</span>}</div>;
}

function Auth({ onAuthenticated }: { onAuthenticated: (token: string, email: string) => void }) {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setSubmitting(true); setError("");
    try { const result = await request<{ access_token: string; email: string }>(`/auth/${mode}`, undefined, { method: "POST", body: JSON.stringify({ email, password }) }); onAuthenticated(result.access_token, result.email); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to continue"); }
    finally { setSubmitting(false); }
  }
  return <main className="auth-shell"><section className="auth-panel" aria-labelledby="auth-title"><p className="eyebrow">Distributed infrastructure monitoring</p><h1 id="auth-title">PulseWatch</h1><p className="muted">See machine health, telemetry, and incidents in one operational view.</p><div className="mode-switch"><button className={mode === "register" ? "selected" : ""} onClick={() => setMode("register")}>Create account</button><button className={mode === "login" ? "selected" : ""} onClick={() => setMode("login")}>Sign in</button></div><form onSubmit={submit}><label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>Password<input type="password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary" disabled={submitting}>{submitting ? "Working..." : mode === "register" ? "Create account" : "Sign in"}</button></form></section></main>;
}

function Dashboard({ token, email, onSignOut }: { token: string; email: string; onSignOut: () => void }) {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [activeMachineId, setActiveMachineId] = useState("");
  const [telemetry, setTelemetry] = useState<Telemetry[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [enrollment, setEnrollment] = useState<{ id: string; agent_token: string } | null>(null);
  const [machineName, setMachineName] = useState("");
  const [hostname, setHostname] = useState("");
  const activeMachine = machines.find((machine) => machine.id === activeMachineId) ?? machines[0];
  const onlineCount = machines.filter((machine) => machine.status === "online").length;
  const activeAlerts = alerts.filter((alert) => alert.state === "active");
  async function refresh() {
    try { const [nextMachines, nextAlerts] = await Promise.all([request<Machine[]>("/machines", token), request<Alert[]>("/alerts", token)]); setMachines(nextMachines); setAlerts(nextAlerts); setActiveMachineId((current) => current || nextMachines[0]?.id || ""); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to refresh dashboard"); }
  }
  useEffect(() => { void refresh(); const interval = window.setInterval(() => void refresh(), 10000); return () => window.clearInterval(interval); }, [token]);
  useEffect(() => {
    const socket = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws/events?token=${encodeURIComponent(token)}`);
    socket.onopen = () => setLive(true);
    socket.onmessage = () => void refresh();
    socket.onclose = () => setLive(false);
    socket.onerror = () => setLive(false);
    return () => socket.close();
  }, [token]);
  useEffect(() => { if (!activeMachine?.id) { setTelemetry([]); return; } void request<Telemetry[]>(`/machines/${activeMachine.id}/telemetry`, token).then(setTelemetry).catch(() => setTelemetry([])); }, [activeMachine?.id, token, machines.length]);
  useEffect(() => { if (!activeMachine?.id) { setRules([]); return; } void request<AlertRule[]>(`/machines/${activeMachine.id}/rules`, token).then(setRules).catch(() => setRules([])); }, [activeMachine?.id, token]);
  async function enrollMachine(event: FormEvent) {
    event.preventDefault();
    try { const result = await request<{ id: string; agent_token: string }>("/machines", token, { method: "POST", body: JSON.stringify({ name: machineName, hostname }) }); setEnrollment(result); setMachineName(""); setHostname(""); await refresh(); setActiveMachineId(result.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to enroll machine"); }
  }
  async function acknowledgeAlert(alertId: number) {
    try { await request(`/alerts/${alertId}/acknowledge`, token, { method: "POST" }); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to acknowledge alert"); }
  }
  async function updateRule(event: FormEvent<HTMLFormElement>, ruleId: number) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    try {
      const rule = await request<AlertRule>(`/alert-rules/${ruleId}`, token, { method: "PUT", body: JSON.stringify({ threshold: Number(values.get("threshold")), severity: values.get("severity"), enabled: values.get("enabled") === "on" }) });
      setRules((current) => current.map((candidate) => candidate.id === rule.id ? rule : candidate));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to update alert rule"); }
  }
  return <main className="app-shell">
    <aside className="sidebar"><div><p className="eyebrow">Control room</p><h1>PulseWatch</h1></div><nav><a className="active" href="#overview">Overview</a><a href="#machines">Machines <span>{machines.length}</span></a><a href="#alerts">Alerts <span>{activeAlerts.length}</span></a></nav><div className="account"><span>{email}</span><button onClick={onSignOut}>Sign out</button></div></aside>
    <section className="workspace">
      <header className="topbar"><div><p className="eyebrow">Infrastructure overview</p><h2>System health</h2></div><span className={error ? "connection issue" : "connection"}>{error || (live ? "Live updates active" : "Connecting live updates")}</span></header>
      <section className="summary" id="overview"><div><span>Monitored machines</span><strong>{machines.length}</strong></div><div><span>Online</span><strong className="healthy">{onlineCount}</strong></div><div><span>Active incidents</span><strong className={activeAlerts.length ? "critical" : "healthy"}>{activeAlerts.length}</strong></div></section>
      <section className="content-grid" id="machines">
        <div className="machine-list"><div className="section-title"><h3>Machines</h3><span>{onlineCount} online</span></div>{machines.length === 0 ? <p className="empty">Enroll a machine to begin receiving telemetry.</p> : machines.map((machine) => <button key={machine.id} className={`machine-row ${activeMachine?.id === machine.id ? "selected" : ""}`} onClick={() => setActiveMachineId(machine.id)}><i className={`status ${machine.status}`} /><span><b>{machine.name}</b><small>{machine.hostname}</small></span><em>{machine.status}</em></button>)}</div>
        <div className="detail-panel"><div className="section-title"><div><h3>{activeMachine?.name ?? "No machine selected"}</h3><span>{activeMachine?.hostname}</span></div>{activeMachine && <span className={`status-label ${activeMachine.status}`}>{activeMachine.status}</span>}</div><div className="metric-grid">{[{ label: "CPU", metric: "cpu_percent" as const, color: "#157f72" }, { label: "Memory", metric: "memory_percent" as const, color: "#c25423" }, { label: "Disk", metric: "disk_percent" as const, color: "#4b61b8" }].map(({ label, metric, color }) => <article key={metric} className="metric"><div><span>{label}</span><b>{telemetry.length ? `${telemetry.at(-1)?.[metric].toFixed(1)}%` : "--"}</b></div><LineChart data={telemetry} metric={metric} color={color} /></article>)}</div>
          <section className="rule-panel"><div className="section-title"><h3>Alert rules</h3><span>{rules.length} configured</span></div>{rules.map((rule) => <form className="rule-row" key={rule.id} onSubmit={(event) => void updateRule(event, rule.id)}><b>{rule.metric.replace("_percent", "")}</b><label>Threshold<input name="threshold" type="number" min="0" max="100" defaultValue={rule.threshold} /></label><label>Severity<select name="severity" defaultValue={rule.severity}><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></label><label className="rule-toggle"><input name="enabled" type="checkbox" defaultChecked={rule.enabled} />Enabled</label><button>Save</button></form>)}</section>
          <p className="last-seen">{activeMachine?.last_heartbeat_at ? `Last heartbeat ${new Date(activeMachine.last_heartbeat_at).toLocaleString()}` : "No heartbeat received"}</p>
        </div>
      </section>
      <section className="lower-grid" id="alerts"><div><div className="section-title"><h3>Active alerts</h3><span>{activeAlerts.length} open</span></div><div className="alerts">{activeAlerts.length === 0 ? <p className="empty">No active incidents.</p> : activeAlerts.map((alert) => <article className={`alert ${alert.severity}`} key={alert.id}><span>{alert.severity}</span><div><b>{alert.machine_name}</b><p>{alert.message}</p></div><div className="alert-actions"><time>{new Date(alert.created_at).toLocaleTimeString()}</time><button onClick={() => void acknowledgeAlert(alert.id)}>Acknowledge</button></div></article>)}</div></div><form className="enroll-form" onSubmit={enrollMachine}><div className="section-title"><h3>Enroll machine</h3></div><label>Name<input value={machineName} onChange={(event) => setMachineName(event.target.value)} placeholder="api-prod-01" required /></label><label>Hostname<input value={hostname} onChange={(event) => setHostname(event.target.value)} placeholder="api-prod-01.local" required /></label><button className="primary">Create enrollment</button>{enrollment && <div className="enrollment"><b>Agent credentials</b><code>Machine ID: {enrollment.id}</code><code>Token: {enrollment.agent_token}</code></div>}</form></section>
    </section>
  </main>;
}

function App() {
  const [session, setSession] = useState(() => ({ token: localStorage.getItem("pulsewatch-token") ?? "", email: localStorage.getItem("pulsewatch-email") ?? "" }));
  const authenticate = (token: string, email: string) => { localStorage.setItem("pulsewatch-token", token); localStorage.setItem("pulsewatch-email", email); setSession({ token, email }); };
  const signOut = () => { localStorage.removeItem("pulsewatch-token"); localStorage.removeItem("pulsewatch-email"); setSession({ token: "", email: "" }); };
  return session.token ? <Dashboard token={session.token} email={session.email} onSignOut={signOut} /> : <Auth onAuthenticated={authenticate} />;
}

createRoot(document.getElementById("root")!).render(<App />);
