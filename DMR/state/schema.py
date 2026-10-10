"""DDL 与模式版本管理。

表结构设计说明见 ``TODO.md`` B8 与 ``PROJECT_STATE.md`` §8；要点：

- **只有 5 张表**：``sessions`` / ``artifacts`` / ``upload_groups`` / ``schema_version``
  / ``meta``。刻意不存能从磁盘重算的信息（只有大小/时长作为缓存列）。
- **不记录分P清单**：用户可在 B 站自行增删分P，本地记录必然与远端不一致。
  上传组只记 ``remote_id``（bvid）这一项远端身份。
- ``recovery`` 的"收养"功能已被移除，因此 **DB 是唯一权威**：磁盘上 DB 不认识的
  文件不会被登记。
"""
from __future__ import annotations

import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

__all__ = ["SCHEMA_VERSION", "apply_schema", "get_schema_version"]

#: 当前模式版本。每次结构变更 +1，并在 MIGRATIONS 中补一条升级脚本。
#: v1 初版；v2 把产物的易变字段收进 JSON ``data`` 列（便于 Artifact 扩展）。
SCHEMA_VERSION = 2

#: 全新库直接按**当前**版本建表（而不是建 v1 再迁移），这样新库与升级后的老库
#: 结构完全一致，避免两条路径产生差异。
_SCHEMA_INITIAL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    taskname      TEXT NOT NULL,
    group_id      TEXT,
    -- 元信息快照：录制开始时已知，供进程被杀后 .part 转正构造 VideoInfo 使用
    platform      TEXT,
    room_id       TEXT,
    room_url      TEXT,
    streamer_name TEXT,
    streamer_uid  TEXT,
    title         TEXT,
    started_at    INTEGER NOT NULL,
    ended_at      INTEGER,
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_task ON sessions(taskname);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    segment_idx INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    -- 需要按状态过滤/回收，故留在列上并建索引
    state       TEXT NOT NULL,
    -- 过期判定与内存回收的基准
    updated_at  INTEGER NOT NULL,
    -- 易变载荷（path / size / duration / danmaku_path / resolution / …）统一放这里，
    -- 使 Artifact 扩展无需改表。字段清单见 DMR/state/payload.py
    data        TEXT NOT NULL DEFAULT '{}',
    UNIQUE(session_id, segment_idx, kind)
);
CREATE INDEX IF NOT EXISTS idx_artifacts_state ON artifacts(state);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);

-- 上传组：只记远端稿件身份，不记分P
CREATE TABLE IF NOT EXISTS upload_groups (
    group_key  TEXT PRIMARY KEY,
    taskname   TEXT NOT NULL,
    target     TEXT NOT NULL,
    account    TEXT,
    engine     TEXT,
    remote_id  TEXT,
    remote_url TEXT,
    state      TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_upload_groups_task ON upload_groups(taskname);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

#: 版本号 -> 从上一版升级到该版的语句列表。
#: 注意：迁移语句里**不要**用 ``IF NOT EXISTS`` 判断列是否存在 —— SQLite 不支持
#: ``ALTER TABLE ADD COLUMN IF NOT EXISTS``，写条件表达式会导致语法错误。
#: 幂等性由 ``apply_schema`` 保证（只在版本号落后时执行）。
MIGRATIONS: dict[int, tuple[str, ...]] = {
    # v1 -> v2：把产物的易变字段收进 JSON 列 data。
    # 不做"判断列是否存在"的花活：v1 的 artifacts 必然有这些列。老库
    # （加 data 列之前的手工库）请直接删除状态库重新开始。
    2: (
        "ALTER TABLE artifacts ADD COLUMN data TEXT NOT NULL DEFAULT '{}'",
        """
        UPDATE artifacts SET data = json_object(
            'path', path,
            'part_path', part_path,
            'danmaku_path', danmaku_path,
            'size', size,
            'duration', duration,
            'resolution', resolution,
            'origin', origin,
            'attempts', attempts,
            'last_error', last_error
        )
        """,
        "ALTER TABLE artifacts DROP COLUMN path",
        "ALTER TABLE artifacts DROP COLUMN part_path",
        "ALTER TABLE artifacts DROP COLUMN danmaku_path",
        "ALTER TABLE artifacts DROP COLUMN size",
        "ALTER TABLE artifacts DROP COLUMN duration",
        "ALTER TABLE artifacts DROP COLUMN resolution",
        "ALTER TABLE artifacts DROP COLUMN origin",
        "ALTER TABLE artifacts DROP COLUMN attempts",
        "ALTER TABLE artifacts DROP COLUMN last_error",
    ),
}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def get_schema_version(conn: sqlite3.Connection) -> int:
    """读取当前模式版本；全新库返回 0。"""
    if not _table_exists(conn, "schema_version"):
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def apply_schema(conn: sqlite3.Connection) -> int:
    """建表并把库升级到 :data:`SCHEMA_VERSION`，返回最终版本。"""
    current = get_schema_version(conn)

    if current == 0:
        conn.executescript(_SCHEMA_INITIAL)
        current = SCHEMA_VERSION
        conn.execute(
            "INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES(?, ?)",
            (current, int(time.time())),
        )
        conn.commit()
        logger.debug("已创建状态库模式 v%d。", current)
        return current

    if current > SCHEMA_VERSION:
        # 比程序还新的库：不擅自降级，让上层决定是否拒绝启动
        raise RuntimeError(
            f"状态库模式版本为 v{current}，高于本程序支持的 v{SCHEMA_VERSION}。"
            "请升级程序，或删除状态库后重新开始。"
        )

    while current < SCHEMA_VERSION:
        target = current + 1
        statements = MIGRATIONS.get(target)
        if not statements:
            raise RuntimeError(f"缺少升级到模式 v{target} 的迁移脚本。")
        for stmt in statements:
            conn.execute(stmt)
        current = target
        logger.info("状态库已升级到模式 v%d。", current)

    conn.execute(
        "INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES(?, ?)",
        (current, int(time.time())),
    )
    conn.commit()
    return current
