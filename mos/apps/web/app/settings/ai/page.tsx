"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Provider = {
  id: string;
  name: string;
  provider_type: string;
  model_default: string | null;
  status: string;
};

type Skill = { skill_code: string; module: string; description: string };

export default function AiHubPage() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    Promise.all([
      apiGet("/api/v1/settings/ai/providers"),
      apiGet("/api/v1/settings/ai/skills/catalog"),
    ])
      .then(([p, s]) => {
        setProviders(p);
        setSkills(s);
      })
      .catch(() => {
        setProviders([]);
        setSkills([]);
      });
  }, []);

  async function testProvider(id: string) {
    const res = await apiPost(`/api/v1/settings/ai/providers/${id}/test`);
    setMsg(t("page.ai.test_result", "Provider test: {status}", { status: res.status || JSON.stringify(res) }));
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.ai.title", "AI Hub")}</h1>
      <p style={{ color: "var(--muted)" }}>{t("page.ai.sub", "Providers and skill bindings.")}</p>
      {msg ? <p>{msg}</p> : null}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.ai.providers", "Providers")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>{t("common.type", "Type")}</th>
              <th>{t("page.ai.model", "Model")}</th>
              <th>{t("common.status", "Status")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {providers.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.provider_type}</td>
                <td>{p.model_default || "—"}</td>
                <td>{p.status}</td>
                <td>
                  <button className="btn" type="button" onClick={() => testProvider(p.id).catch(() => setMsg(t("page.ai.test_fail", "Test failed")))}>
                    {t("common.test", "Test")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.ai.skills", "Skill catalog")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.ai.skill", "Skill")}</th>
              <th>{t("page.ai.module", "Module")}</th>
              <th>{t("page.ai.description", "Description")}</th>
            </tr>
          </thead>
          <tbody>
            {skills.map((s) => (
              <tr key={s.skill_code}>
                <td>{s.skill_code}</td>
                <td>{s.module}</td>
                <td>{s.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
