"""email_messages 增加 folder 列 + HTML 正文回填纯文本

Revision ID: e3f5a7b9c1d2
Revises: d2e3f4a5b6c7
Create Date: 2026-10-25 10:00:00.000000

邮件复核增强（用户反馈：清单不全 / 无时间列 / HTML 污染）：

1. ``email_messages.folder``：记录邮件所在的 Graph 文件夹（inbox /
   sentitems / 自定义子文件夹 id）。历史行统一回填 ``inbox``（此前同步
   只拉收件箱）。同步端点由此支持多文件夹拉取与前端 Tab 浏览。

2. 索引 ``ix_email_messages_tenant_folder``：列表页按
   tenant + folder 过滤是主查询路径。

3. 数据回填：历史行的 ``body_text`` / ``parse_result`` 是 Graph 的原始
   HTML（解析器把标签吞进了字段）。统一过 ``html_to_text`` 转纯文本 ——
   不回填的话这些行因 message_id 去重永远不会重新拉取，脏数据永久留存。

迁移约定（见 ``alembic/README.md``）：全部幂等 —— 列已存在则跳过，
回填只处理仍含 ``<`` 的行，重复执行不报错。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e3f5a7b9c1d2"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _column(table: str, column: str):
    if not _has_table(table):
        return None
    for col in _inspector().get_columns(table):
        if col["name"] == column:
            return col
    return None


def _clean_parse_result(value):
    """parse_result JSON 值递归清洗：字符串值含标签则转纯文本。"""
    from app.services.html_to_text import html_to_text

    if isinstance(value, str):
        return html_to_text(value) if "<" in value else value
    if isinstance(value, dict):
        return {k: _clean_parse_result(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_parse_result(v) for v in value]
    return value


def upgrade() -> None:
    # —— 1. folder 列 ————————————————————————————————————————————————
    if _has_table("email_messages") and _column("email_messages", "folder") is None:
        op.add_column(
            "email_messages",
            sa.Column("folder", sa.Text(), nullable=False, server_default="inbox"),
        )

    # —— 2. 租户 + 文件夹复合索引 ————————————————————————————————————
    if _has_table("email_messages"):
        existing = {ix["name"] for ix in _inspector().get_indexes("email_messages")}
        if "ix_email_messages_tenant_folder" not in existing:
            op.create_index(
                "ix_email_messages_tenant_folder",
                "email_messages",
                ["tenant_id", "folder"],
            )

    # —— 3. 历史 HTML 数据回填纯文本 ————————————————————————————————
    import json

    from app.services.html_to_text import html_to_text

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, body_text, parse_result FROM email_messages")
    ).fetchall()
    for row_id, body_text, parse_result in rows:
        new_body = html_to_text(body_text) if body_text and "<" in body_text else body_text
        # parse_result 在 SQLite 里是 JSON 文本、在 PG 里是 dict —— 统一解码后清洗
        decoded = parse_result
        if isinstance(decoded, str) and decoded:
            try:
                decoded = json.loads(decoded)
            except (ValueError, TypeError):
                decoded = None
        new_result = parse_result
        if decoded is not None:
            cleaned = _clean_parse_result(decoded)
            if cleaned != decoded:
                new_result = json.dumps(cleaned, ensure_ascii=False)
        if new_body != body_text or new_result != parse_result:
            bind.execute(
                sa.text(
                    "UPDATE email_messages SET body_text = :body, parse_result = :result "
                    "WHERE id = :id"
                ),
                {"body": new_body, "result": new_result, "id": row_id},
            )


def downgrade() -> None:
    if _column("email_messages", "folder") is not None:
        op.drop_index("ix_email_messages_tenant_folder", table_name="email_messages")
        op.drop_column("email_messages", "folder")
