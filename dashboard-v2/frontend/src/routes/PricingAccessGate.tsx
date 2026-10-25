import { FormEvent, ReactNode, useEffect, useState } from "react";

import { pricingAuthApi } from "../lib/api";

type PricingAccessGateProps = {
  children: ReactNode;
  title?: string;
  description?: string;
  buttonLabel?: string;
};

export function PricingAccessGate({
  children,
  title = "Pricing Intelligence",
  description = "此页面包含敏感价格信息，请输入访问密码。",
  buttonLabel = "进入 Pricing",
}: PricingAccessGateProps) {
  const [status, setStatus] = useState<"checking" | "locked" | "open">("checking");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    pricingAuthApi.status()
      .then(({ authenticated }) => setStatus(authenticated ? "open" : "locked"))
      .catch(() => setStatus("locked"));
  }, []);

  async function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await pricingAuthApi.login(password);
      setStatus("open");
    } catch {
      setError("密码不正确，请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "open") return <>{children}</>;

  return <div className="pricing-gate-wrap">
    <section className="pricing-gate" aria-busy={status === "checking"}>
      <div className="pricing-gate-icon" aria-hidden="true">{status === "checking" ? "…" : "🔒"}</div>
      <p className="pricing-gate-kicker">RESTRICTED ACCESS</p>
      <h1>{title}</h1>
      {status === "checking" ? <p>Checking access…</p> : <>
        <p>{description}</p>
        <form onSubmit={unlock}>
          <label htmlFor="pricing-password">访问密码</label>
          <input
            id="pricing-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            autoFocus
            required
          />
          {error && <div className="pricing-gate-error" role="alert">{error}</div>}
          <button type="submit" disabled={submitting}>{submitting ? "验证中…" : buttonLabel}</button>
        </form>
      </>}
    </section>
  </div>;
}
