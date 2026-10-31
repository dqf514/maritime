"use client";

/**
 * 团队看板 —— 任务中心「团队」Tab 的组织视角。
 *
 * 一列一个部门，列内按人分组，每人显示在办数 / 逾期数与自己的任务行。
 * 「任务分明、权责分明」要看得见：一眼看出谁手上压着多少、谁逾期了、
 * 每个人是谁的下属（汇报线）。
 *
 * 部门信息来自 ``/api/v1/tasks/people``（主部门优先）；没有部门的人
 * 归到「未分配部门」列。任务按主责人分组 —— 主责唯一（协作人只是协办）。
 */

import { TaskOut, TaskPerson } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { TaskRow, taskDueInfo } from "@/components/TaskRow";

type Props = {
  rows: TaskOut[];
  people: TaskPerson[];
  busyId?: string;
  onComplete?: (task: TaskOut) => void;
  onReopen?: (task: TaskOut) => void;
  onOpen?: (task: TaskOut) => void;
};

type PersonCell = {
  person: TaskPerson;
  tasks: TaskOut[];
  open: number;
  overdue: number;
};

type DeptCol = {
  key: string;
  name: string;
  people: PersonCell[];
  open: number;
  overdue: number;
};

export function TaskTeamBoard({ rows, people, busyId = "", onComplete, onReopen, onOpen }: Props) {
  const { t } = useI18n();

  // 任务按主责人归组
  const byAssignee = new Map<string, TaskOut[]>();
  for (const row of rows) {
    const key = row.assignee?.id || "";
    const list = byAssignee.get(key);
    if (list) list.push(row);
    else byAssignee.set(key, [row]);
  }

  // 人 → 部门（保持 people 的顺序 = 后端按邮箱排序）
  const deptOrder: string[] = [];
  const deptName = new Map<string, string>();
  const peopleOfDept = new Map<string, TaskPerson[]>();
  for (const p of people) {
    const key = p.org_unit_code || "OTHER";
    if (!deptName.has(key)) {
      deptName.set(key, p.org_unit_name || t("page.tasks.dept_other", "Unassigned department"));
      deptOrder.push(key);
      peopleOfDept.set(key, []);
    }
    peopleOfDept.get(key)!.push(p);
  }

  const cols: DeptCol[] = deptOrder.map((key) => {
    const cells: PersonCell[] = (peopleOfDept.get(key) || []).map((person) => {
      const tasks = byAssignee.get(person.id) || [];
      let open = 0;
      let overdue = 0;
      for (const task of tasks) {
        if (task.status !== "done" && task.status !== "cancelled") {
          open += 1;
          if (taskDueInfo(task, t)?.overdue) overdue += 1;
        }
      }
      return { person, tasks, open, overdue };
    });
    return {
      key,
      name: deptName.get(key) || key,
      people: cells,
      open: cells.reduce((n, c) => n + c.open, 0),
      overdue: cells.reduce((n, c) => n + c.overdue, 0),
    };
  });

  // 没有主责人的任务（还没派下去）单独一列 —— 不该悄悄消失
  const unassigned = byAssignee.get("") || [];
  if (unassigned.length) {
    cols.push({
      key: "UNASSIGNED",
      name: t("page.tasks.dept_unassigned", "Unassigned"),
      people: [
        {
          person: {
            id: "",
            email: "",
            full_name: null,
            manager_user_id: null,
            manager_name: null,
            is_report: false,
          },
          tasks: unassigned,
          open: unassigned.filter((x) => x.status !== "done" && x.status !== "cancelled").length,
          overdue: unassigned.filter((x) => taskDueInfo(x, t)?.overdue).length,
        },
      ],
      open: unassigned.filter((x) => x.status !== "done" && x.status !== "cancelled").length,
      overdue: unassigned.filter((x) => taskDueInfo(x, t)?.overdue).length,
    });
  }

  return (
    <div className="tk-board">
      {cols.map((col) => (
        <section key={col.key} className="tk-board-col">
          <header className="tk-board-head">
            <strong>{col.name}</strong>
            <span className="muted">
              {col.open} {t("page.tasks.stat_open", "open")} · {col.overdue}{" "}
              {t("page.tasks.stat_overdue", "overdue")}
            </span>
          </header>
          {col.people.map((cell) => (
            <div key={cell.person.id || "unassigned"} className="tk-board-person">
              <div className="tk-board-person-head">
                <span className="tk-board-person-name">
                  {cell.person.full_name || cell.person.email || t("page.tasks.unassigned", "Unassigned")}
                </span>
                {cell.person.manager_name ? (
                  <span className="muted">
                    {t("page.tasks.reports_to", "reports to")} {cell.person.manager_name}
                  </span>
                ) : null}
                <span className="muted">
                  {cell.open} {t("page.tasks.stat_open", "open")}
                  {cell.overdue ? ` · ${cell.overdue} ${t("page.tasks.stat_overdue", "overdue")}` : ""}
                </span>
              </div>
              {cell.tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  busy={busyId === task.id}
                  onComplete={onComplete}
                  onReopen={onReopen}
                  onOpen={onOpen}
                />
              ))}
              {!cell.tasks.length ? <p className="muted tk-board-empty">{t("page.tasks.no_tasks", "No tasks.")}</p> : null}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
