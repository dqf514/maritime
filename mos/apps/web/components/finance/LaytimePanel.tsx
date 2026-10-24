"use client";

// 3.6：Laytime 面板（自取数 + 手工/SOF 创建 + 计算/定稿/索赔动作 + 删除）。

import { msgOf, handled } from "@/lib/errors";
import { FormEvent, useCallback, useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { DateTimeInput } from "@/components/DateInput";
import { Num } from "@/components/Num";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiList, apiPost } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type VoyageRef = { id: string; voyage_no: string };
type Laytime = {
  id: string;
  voyage_id: string | null;
  status: string;
  results: { amount?: number };
};

/** 数字输入解析：空串 → null；非法输入 → NaN（调用方必须报错，禁止静默转 0）。 */
function numOrNull(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

export function LaytimePanel() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();

  const [rows, setRows] = useState<Laytime[]>([]);
  const [total, setTotal] = useState(0);
  const [version, setVersion] = useState(0);
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [busy, setBusy] = useState(false);
  // P1-4：主列表取数失败 → 三态错误；航次参照列表失败 → 单独提示，不拖垮主列表
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refErr, setRefErr] = useState<string | null>(null);
  // 首次成功加载后，后续刷新不再整表 spinner（避免卸载 DataGrid 丢失排序/列布局）
  const loadedOnce = useRef(false);

  const [ltVoyage, setLtVoyage] = useState("");
  const [ltAllowed, setLtAllowed] = useState("72");
  const [ltCargoQty, setLtCargoQty] = useState("");
  const [ltLoadRate, setLtLoadRate] = useState("");
  const [ltTurn, setLtTurn] = useState("6");
  const [ltDem, setLtDem] = useState("24000");
  const [ltDes, setLtDes] = useState("12000");
  const [ltE1Start, setLtE1Start] = useState("2026-09-01T08:00");
  const [ltE1End, setLtE1End] = useState("2026-09-04T20:00");
  const [ltE2Start, setLtE2Start] = useState("2026-09-02T00:00");
  const [ltE2End, setLtE2End] = useState("2026-09-02T12:00");
  const [sofPortCallId, setSofPortCallId] = useState("");
  const [sofAllowed, setSofAllowed] = useState("");
  const [sofTerms, setSofTerms] = useState("");
  const ctx = useContextMenu<Laytime>();

  const loadList = useCallback(async () => {
    if (!loadedOnce.current) setLoading(true);
    setErr(null);
    try {
      const pg = await apiList<Laytime>("/api/v1/laytimes", { limit, offset: (page - 1) * limit });
      setRows(pg.items);
      setTotal(pg.total);
      loadedOnce.current = true;
      if (!pg.items.length && pg.total > 0 && page > 1) setQuery({ page: Math.ceil(pg.total / limit) });
    } catch (ex) {
      setRows([]);
      setTotal(0);
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [limit, page, setQuery]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    loadList().catch(handled);
  }, [loadList, version]);

  useEffect(() => {
    apiGet("/api/v1/voyages/options")
      .then((v: VoyageRef[]) => {
        setVoyages(v);
        setRefErr(null);
      })
      .catch((ex) => {
        setVoyages([]);
        setRefErr(msgOf(ex));
      });
  }, []);

  async function removeLaytime() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/laytimes/${selected}`);
      setSelected(null);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      refresh();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createLaytime(e: FormEvent) {
    e.preventDefault();
    // P1-24：非法数字必须报错并中止，不能静默转 0
    const turn = numOrNull(ltTurn);
    const dem = numOrNull(ltDem);
    const des = numOrNull(ltDes);
    if (turn === null || Number.isNaN(turn)) {
      toast.error(t("page.finance.bad_number", "Enter a valid number"));
      return;
    }
    if (dem === null || Number.isNaN(dem)) {
      toast.error(t("page.finance.bad_number", "Enter a valid number"));
      return;
    }
    if (des === null || Number.isNaN(des)) {
      toast.error(t("page.finance.bad_number", "Enter a valid number"));
      return;
    }
    let allowed: number | null = null;
    if (ltAllowed.trim() !== "") {
      allowed = numOrNull(ltAllowed);
      if (allowed === null || Number.isNaN(allowed)) {
        toast.error(t("page.finance.bad_number", "Enter a valid number"));
        return;
      }
    }
    let cargoQty: number | null = null;
    let loadRate: number | null = null;
    const hasQty = ltCargoQty.trim() !== "";
    const hasRate = ltLoadRate.trim() !== "";
    if (hasQty !== hasRate) {
      // 两项必须成对填写，否则静默丢弃一半输入等于丢数据
      toast.error(t("page.finance.lt_cargo_rate_pair", "Cargo qty and load rate must both be filled"));
      return;
    }
    if (hasQty && hasRate) {
      cargoQty = numOrNull(ltCargoQty);
      loadRate = numOrNull(ltLoadRate);
      if (cargoQty === null || Number.isNaN(cargoQty) || loadRate === null || Number.isNaN(loadRate)) {
        toast.error(t("page.finance.bad_number", "Enter a valid number"));
        return;
      }
    }
    setBusy(true);
    try {
      const inputs: Record<string, unknown> = {
        turn_time_hours: turn,
        demurrage_rate_per_day: dem,
        despatch_rate_per_day: des,
        events: [
          { start: ltE1Start.length === 16 ? `${ltE1Start}:00` : ltE1Start, end: ltE1End.length === 16 ? `${ltE1End}:00` : ltE1End, excluded: false },
          { start: ltE2Start.length === 16 ? `${ltE2Start}:00` : ltE2Start, end: ltE2End.length === 16 ? `${ltE2End}:00` : ltE2End, excluded: true },
        ],
      };
      if (allowed !== null) inputs.allowed_hours = allowed;
      if (cargoQty !== null && loadRate !== null) {
        inputs.cargo_qty = cargoQty;
        inputs.load_rate_per_day = loadRate;
      }
      const lt = await apiPost("/api/v1/laytimes", { voyage_id: ltVoyage || null, inputs });
      setSelected(lt.id);
      toast.success(t("page.finance.lt_created", "Laytime draft created"));
      refresh();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createFromSof(e: FormEvent) {
    e.preventDefault();
    if (!sofPortCallId.trim()) {
      toast.error(t("page.finance.sof_need_pc", "请填写 port_call_id"));
      return;
    }
    let sofAllowedNum: number | null = null;
    if (sofAllowed.trim() !== "") {
      sofAllowedNum = numOrNull(sofAllowed);
      if (sofAllowedNum === null || Number.isNaN(sofAllowedNum)) {
        toast.error(t("page.finance.bad_number", "Enter a valid number"));
        return;
      }
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = { port_call_id: sofPortCallId.trim() };
      if (sofAllowedNum !== null) body.allowed_hours = sofAllowedNum;
      if (sofTerms) body.terms = sofTerms;
      const lt = await apiPost("/api/v1/laytimes/from-sof", body);
      setSelected(lt.id);
      toast.success(t("page.finance.lt_sof_ok", "已从 SOF 生成并计算"));
      refresh();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      if (ex?.status === 422 && code === "ALLOWED_HOURS_REQUIRED") {
        toast.error(t("page.finance.sof_allowed_required", "无法从租约推导允许小时，请填写 allowed hours"));
      } else if (ex?.status === 422 && code === "INSUFFICIENT_SOF") {
        toast.error(t("page.finance.sof_insufficient", "SOF 事件不足（至少需要 COMMENCED 与 COMPLETED）"));
      } else {
        toast.error(msgOf(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function calc(id: string) {
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/laytimes/${id}/calculate`);
      toast.success(t("page.finance.lt_calc", "Laytime amount {amt}", { amt: fmt(res.results?.amount) }));
      setSelected(id);
      refresh();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function finalize(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/laytimes/${id}/finalize`);
      toast.success(t("page.finance.lt_final", "Laytime finalized"));
      refresh();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function claimFrom(lt: Laytime) {
    setBusy(true);
    try {
      const claim = await apiPost("/api/v1/claims", {
        voyage_id: lt.voyage_id,
        laytime_id: lt.id,
        claim_type: (lt.results as { result_type?: string })?.result_type === "despatch" ? "despatch" : "demurrage",
        amount: lt.results?.amount ?? undefined,
      });
      toast.success(t("page.finance.claim_ok", "Claim {no} created", { no: claim.claim_no }));
      router.push("/finance?tab=claims");
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const cols = useMemo<ColumnDef<Laytime>[]>(
    () => [
      { key: "id", title: "ID", render: (v) => String(v).slice(0, 8) },
      {
        key: "voyage_id",
        title: t("page.voyages.list", "Voyages"),
        render: (v) => (v ? voyages.find((x) => x.id === v)?.voyage_no || String(v).slice(0, 8) : "—"),
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        render: (v) => (
          <>
            {String(v)}
            {v === "finalized" ? (
              <span className="badge badge-warn" style={{ marginLeft: "0.4rem" }}>
                {t("page.finance.lt_locked", "已锁定")}
              </span>
            ) : null}
          </>
        ),
      },
      { key: "results.amount", title: t("common.amount", "Amount"), align: "right", value: (r) => r.results?.amount ?? null, render: (v) => <Num v={v as number | null} digits={2} /> },
      {
        key: "actions",
        title: "",
        render: (_v, r) => (
          <div className="desk-toolbar" style={{ margin: 0 }}>
            {r.status === "draft" || r.status === "calculated" ? (
              <button className="btn btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); calc(r.id); }}>
                {t("page.estimates.calculate", "Calculate")}
              </button>
            ) : null}
            {r.status === "calculated" ? (
              <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); finalize(r.id); }}>
                {t("page.finance.finalize", "Finalize")}
              </button>
            ) : null}
            {r.status === "finalized" || r.status === "calculated" ? (
              <button className="btn btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); claimFrom(r); }}>
                {t("page.finance.create_claim", "Create claim")}
              </button>
            ) : null}
            <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); router.push(`/finance/laytimes/${r.id}`); }}>
              {t("page.finance.lt_export", "计算书 / 打印")}
            </button>
          </div>
        ),
      },
    ],
    [t, router],
  );

  const menuItems = (row: Laytime): ContextMenuItem[] => {
    const items: ContextMenuItem[] = [
      {
        key: "open",
        label: t("page.finance.lt_export", "计算书 / 打印"),
        onClick: () => router.push(`/finance/laytimes/${row.id}`),
      },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
      { key: "div", divider: true, label: "" },
    ];
    if (row.status === "draft" || row.status === "calculated") {
      items.push({ key: "calc", label: t("page.estimates.calculate", "Calculate"), onClick: () => calc(row.id) });
    }
    if (row.status === "calculated") {
      items.push({ key: "finalize", label: t("page.finance.finalize", "Finalize"), onClick: () => finalize(row.id) });
    }
    if (row.status === "finalized" || row.status === "calculated") {
      items.push({ key: "claim", label: t("page.finance.create_claim", "Create claim"), onClick: () => claimFrom(row) });
    }
    return items;
  };

  return (
    <>
      {refErr ? (
        <p className="flash-err">
          {t("page.finance.ref_load_failed", "Some reference lists could not be loaded")}: {refErr}
        </p>
      ) : null}
      <form className="panel" onSubmit={createLaytime}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_laytime", "New laytime")}</h3>
        <div className="form-grid">
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={ltVoyage} onChange={(e) => setLtVoyage(e.target.value)}>
              <option value="">—</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.finance.allowed_h", "Allowed hours")}
            <input type="number" step="any" value={ltAllowed} onChange={(e) => setLtAllowed(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.cargo_qty", "Cargo qty")}
            <input type="number" step="any" value={ltCargoQty} onChange={(e) => setLtCargoQty(e.target.value)} />
          </label>
          <label>
            {t("page.finance.load_rate", "Load rate / day")}
            <input type="number" step="any" value={ltLoadRate} onChange={(e) => setLtLoadRate(e.target.value)} />
          </label>
          <label>
            {t("page.finance.turn_time", "Turn time (h)")}
            <input type="number" step="any" value={ltTurn} onChange={(e) => setLtTurn(e.target.value)} />
          </label>
          <label>
            {t("page.finance.dem_rate", "Demurrage / day")}
            <input type="number" step="any" value={ltDem} onChange={(e) => setLtDem(e.target.value)} />
          </label>
          <label>
            {t("page.finance.des_rate", "Despatch / day")}
            <input type="number" step="any" value={ltDes} onChange={(e) => setLtDes(e.target.value)} />
          </label>
          <label>
            {t("page.finance.ev1_start", "Event 1 start")}
            <DateTimeInput value={ltE1Start} onChange={setLtE1Start} />
          </label>
          <label>
            {t("page.finance.ev1_end", "Event 1 end")}
            <DateTimeInput value={ltE1End} onChange={setLtE1End} />
          </label>
          <label>
            {t("page.finance.ev2_start", "Event 2 start (excluded)")}
            <DateTimeInput value={ltE2Start} onChange={setLtE2Start} />
          </label>
          <label>
            {t("page.finance.ev2_end", "Event 2 end")}
            <DateTimeInput value={ltE2End} onChange={setLtE2End} />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      <form className="panel" onSubmit={createFromSof}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_from_sof", "从 SOF 生成")}</h3>
        <div className="form-grid">
          <label>
            {t("page.finance.port_call_id", "Port call ID")}
            <input value={sofPortCallId} onChange={(e) => setSofPortCallId(e.target.value)} required />
          </label>
          <label>
            {t("page.finance.allowed_h", "Allowed hours")}
            <input type="number" step="any" value={sofAllowed} onChange={(e) => setSofAllowed(e.target.value)} placeholder={t("common.optional", "Optional")} />
          </label>
          <label>
            {t("page.charters.laytime_terms", "Laytime terms")}
            <input value={sofTerms} onChange={(e) => setSofTerms(e.target.value)} placeholder="SHINC / SHEX…" />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      <div className="panel">
        {selected ? (
          <div className="desk-toolbar" style={{ marginTop: 0 }}>
            <span className="muted">
              {t("page.finance.lt_selected", "已选滞期")} {selected.slice(0, 8)}
            </span>
            <button
              className="btn btn-danger btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                setConfirmDel(true)
              }
            >
              {t("common.delete", "删除")}
            </button>
          </div>
        ) : null}
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!rows.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => loadList()}
        >
          <DataGrid<Laytime>
            data={rows}
            columns={cols}
            rowKey={(r) => r.id}
            storageKey="finance.laytimes"
            emptyText={t("common.empty", "No records")}
            onRowClick={(r) => setSelected(r.id)}
            onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
          />
        </StateView>
        <div className="desk-toolbar">
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={page <= 1}
            onClick={() => setQuery({ page: page > 2 ? page - 1 : null }, { resetPage: false })}
            aria-label={t("common.prev_page", "Previous page")}
          >
            ←
          </button>
          <span className="muted">
            {page} / {Math.max(1, Math.ceil(total / limit))}
          </span>
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={page * limit >= total}
            onClick={() => setQuery({ page: page + 1 }, { resetPage: false })}
            aria-label={t("common.next_page", "Next page")}
          >
            →
          </button>
        </div>
      </div>

      <ContextMenu controller={ctx} items={menuItems} />

      <ConfirmDialog
        open={confirmDel}
        title={t("common.confirm", "确认操作")}
        message={t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored.")}
        danger
        onConfirm={() => {
          setConfirmDel(false);
          removeLaytime();
        }}
        onCancel={() => setConfirmDel(false)}
      />
    </>
  );
}
