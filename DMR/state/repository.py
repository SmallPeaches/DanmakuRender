"""SQLite 状态仓储。

职责：把"录制会话 / 产物 / 上传组"的状态持久化，使进程重启后能继续处理未完成的工作。
（设计背景见 ``TODO.md`` B8 的 P1 与 ``PROJECT_STATE.md`` §8。）

线程模型
--------
录制线程与事件线程都会写状态，因此：

- 连接以 ``check_same_thread=False`` 建立；
- 所有写操作由 :attr:`StateRepository._lock` 串行化（本模块的单进程用途下足够，
  且避免了 SQLite 的 ``database is locked`` 抖动）；
- ``timeout`` 与 ``busy_timeout`` 都设为 5 秒，容忍偶发并发。

时间
----
所有时间戳都是 **Unix 秒（int）**。对账与过期判定都以 ``updated_at`` 为基准，
因此任何状态变更都必须刷新它 —— 相关方法已统一处理。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Iterable, Mapping, Sequence

from .enums import (
    ArtifactKind,
    ArtifactState,
    UploadGroupState,
    coerce_artifact_state,
    coerce_upload_group_state,
)
from .payload import MUTABLE_PAYLOAD_FIELDS, decode_payload, encode_payload
from .schema import apply_schema

logger = logging.getLogger(__name__)

__all__ = [
    "SessionRecord",
    "ArtifactRecord",
    "UploadGroupRecord",
    "StateRepository",
]


#: 留在列上（结构化、可查询）的产物字段。其余可字段收进 ``data`` JSON 列。
#: 这份元组由 :data:`MUTABLE_PAYLOAD_FIELDS` 反推得到，保证"列 + JSON = 全部字段"，
#: 新增字段时只需在 payload.py 里登记一次。
_ARTIFACT_COLUMN_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "session_id",
    "segment_idx",
    "kind",
    "state",
    "updated_at",
)


def _now() -> int:
    return int(time.time())


def _row_to_kwargs(row: sqlite3.Row) -> dict:
    """把一行 ``artifacts`` 还原成 :class:`ArtifactRecord` 的构造参数。

    列上的字段直接取，``data`` 里的字段解 JSON 后合并。**只保留已知字段**：
    若载荷里有本程序版本尚不认识的键（例如降级运行），直接传给 dataclass 会
    ``TypeError``；过滤掉即可保证前向/后向兼容。
    """
    kwargs = {name: row[name] for name in _ARTIFACT_COLUMN_FIELDS}
    payload = decode_payload(row["data"])
    for name in MUTABLE_PAYLOAD_FIELDS:
        if name in payload:
            kwargs[name] = payload[name]
    return kwargs


@dataclass
class SessionRecord:
    session_id: str
    taskname: str
    started_at: int
    updated_at: int
    group_id: str | None = None
    platform: str | None = None
    room_id: str | None = None
    room_url: str | None = None
    streamer_name: str | None = None
    streamer_uid: str | None = None
    title: str | None = None
    ended_at: int | None = None

    @property
    def is_ended(self) -> bool:
        return self.ended_at is not None


@dataclass
class ArtifactRecord:
    artifact_id: str
    session_id: str
    segment_idx: int
    kind: ArtifactKind
    state: ArtifactState
    updated_at: int
    path: str | None = None
    part_path: str | None = None
    danmaku_path: str | None = None
    size: int | None = None
    duration: float | None = None
    resolution: tuple[int, int] | None = None
    origin: str | None = None
    attempts: int = 0
    last_error: str | None = None
    #: 录制当时的 ``VideoInfo``（已 JSON 化）。用于重启后重建产物并重新驱动处理。
    video_info: dict | None = None

    @property
    def is_terminal(self) -> bool:
        from .enums import TERMINAL_ARTIFACT_STATES

        return self.state in TERMINAL_ARTIFACT_STATES


@dataclass
class UploadGroupRecord:
    group_key: str
    taskname: str
    target: str
    state: UploadGroupState
    created_at: int
    updated_at: int
    account: str | None = None
    engine: str | None = None
    remote_id: str | None = None
    remote_url: str | None = None
    expires_at: int | None = None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= _now()


def _row_to_session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        taskname=row["taskname"],
        group_id=row["group_id"],
        platform=row["platform"],
        room_id=row["room_id"],
        room_url=row["room_url"],
        streamer_name=row["streamer_name"],
        streamer_uid=row["streamer_uid"],
        title=row["title"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        updated_at=row["updated_at"],
    )


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
    """还原产物记录。

    ``kind`` / ``state`` 做容错（未知值降级并告警），其余字段由 ``data`` JSON
    与列拼接而来 —— 见 :func:`_row_to_kwargs`。
    """
    try:
        kind = ArtifactKind(row["kind"])
    except ValueError:
        logger.warning("产物 %s 的 kind=%r 未知，按 src_video 处理。",
                       row["artifact_id"], row["kind"])
        kind = ArtifactKind.SOURCE
    kwargs = _row_to_kwargs(row)
    kwargs["kind"] = kind
    kwargs["state"] = coerce_artifact_state(row["state"],
                                           context=row["artifact_id"])
    return ArtifactRecord(**kwargs)


def _row_to_group(row: sqlite3.Row) -> UploadGroupRecord:
    return UploadGroupRecord(
        group_key=row["group_key"],
        taskname=row["taskname"],
        target=row["target"],
        account=row["account"],
        engine=row["engine"],
        remote_id=row["remote_id"],
        remote_url=row["remote_url"],
        state=coerce_upload_group_state(row["state"], context=row["group_key"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
    )


class StateRepository:
    """状态库。所有方法都是同步的、线程安全的。

    用法::

        repo = StateRepository("logs/dmr_state.db")
        repo.open()
        ...
        repo.close()
    """

    def __init__(self, db_path: str | os.PathLike = "logs/dmr_state.db") -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self.schema_version: int = 0

    # ------------------------------------------------------------------ 连接

    def open(self) -> "StateRepository":
        with self._lock:
            if self._conn is not None:
                return self

            if self.db_path != ":memory:":
                parent = os.path.dirname(os.path.abspath(self.db_path))
                if parent:
                    os.makedirs(parent, exist_ok=True)

            conn = sqlite3.connect(self.db_path, timeout=5.0,
                                   check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # WAL：单文件、崩溃安全、读写并发友好
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                self.schema_version = apply_schema(conn)
            except Exception:
                # 建表/迁移失败时不要留下已打开但无人持有的连接
                conn.close()
                raise
            self._conn = conn
            return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "StateRepository":
        return self.open()

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("状态库尚未打开，请先调用 open()。")
        return self._conn

    # ------------------------------------------------------------------ 会话

    def create_session(
        self,
        session_id: str,
        taskname: str,
        *,
        group_id: str | None = None,
        platform: str | None = None,
        room_id: str | None = None,
        room_url: str | None = None,
        streamer_name: str | None = None,
        streamer_uid: str | None = None,
        title: str | None = None,
        started_at: int | None = None,
    ) -> SessionRecord:
        """登记一场直播。已存在则返回既有记录（幂等）。"""
        with self._lock:
            existing = self.get_session(session_id)
            if existing is not None:
                return existing
            now = _now()
            self.conn.execute(
                "INSERT INTO sessions(session_id, taskname, group_id, platform,"
                " room_id, room_url, streamer_name, streamer_uid, title,"
                " started_at, ended_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?)",
                (session_id, taskname, group_id, platform, room_id, room_url,
                 streamer_name, streamer_uid, title,
                 started_at if started_at is not None else now, now),
            )
            self.conn.commit()
            return self.get_session(session_id)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            return _row_to_session(row) if row else None

    def end_session(self, session_id: str, ended_at: int | None = None) -> None:
        """标记场次结束（下播）。"""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, updated_at=? WHERE session_id=?",
                (ended_at if ended_at is not None else _now(), _now(), session_id),
            )
            self.conn.commit()

    def touch_session(self, session_id: str) -> None:
        """刷新场次的活跃时间（有新分段产出时调用）。"""
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?",
                (_now(), session_id),
            )
            self.conn.commit()

    def list_sessions(self, taskname: str | None = None) -> list[SessionRecord]:
        with self._lock:
            if taskname is None:
                rows = self.conn.execute(
                    "SELECT * FROM sessions ORDER BY started_at"
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM sessions WHERE taskname=? ORDER BY started_at",
                    (taskname,),
                ).fetchall()
            return [_row_to_session(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        """删除场次（并级联删除其产物）。"""
        with self._lock:
            self.conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self.conn.commit()

    # ------------------------------------------------------------------ 产物

    def _raw_payload(self, artifact_id: str) -> dict:
        """读取某产物的原始 ``data`` 载荷（不存在或无记录时为空 dict）。

        直接读 JSON 列而不是走 :class:`ArtifactRecord`：写入时只需要载荷本身，
        避免为了改一个字段而把整行反序列化再拼回去。
        """
        row = self.conn.execute(
            "SELECT data FROM artifacts WHERE artifact_id=?", (artifact_id,)
        ).fetchone()
        if row is None:
            return {}
        return decode_payload(row["data"])

    def _merge_payload(self, existing: dict, updates: dict) -> str:
        """把本次更新合并进已有载荷，并交给 :func:`encode_payload` 序列化。

        只保留**已知且本次写入过**的键：载荷保持精简，缺失字段由
        :class:`ArtifactRecord` 的默认值兜住，因此部分载荷是完全正常的。
        未知键会被剔除，防止脏数据在库里长期堆积。
        """
        merged = {k: v for k, v in existing.items()
                  if k in MUTABLE_PAYLOAD_FIELDS}
        merged.update({k: v for k, v in updates.items()
                       if k in MUTABLE_PAYLOAD_FIELDS})
        # 借用一个轻量对象走同一个序列化出口，避免此处重复 JSON 细节
        return encode_payload(SimpleNamespace(**merged))

    def upsert_artifact(
        self,
        artifact_id: str,
        session_id: str,
        segment_idx: int,
        kind: ArtifactKind | str,
        state: ArtifactState | str,
        *,
        path: str | None = None,
        part_path: str | None = None,
        danmaku_path: str | None = None,
        size: int | None = None,
        duration: float | None = None,
        resolution=None,
        origin: str | None = None,
        attempts: int | None = None,
        last_error: str | None = None,
        video_info: dict | None = None,
    ) -> ArtifactRecord:
        kind = ArtifactKind(kind)
        state = ArtifactState(state)
        updates = {
            "path": path,
            "part_path": part_path,
            "danmaku_path": danmaku_path,
            "size": size,
            "duration": duration,
            "resolution": resolution,
            "origin": origin,
            "attempts": attempts if attempts is not None else 0,
            "last_error": last_error,
            "video_info": video_info,
        }
        with self._lock:
            now = _now()
            existing = self._raw_payload(artifact_id)
            # 与旧列语义保持一致：未显式给出的可选字段沿用已有值（COALESCE 语义），
            # 而 part_path / last_error 总是被本次调用覆盖。
            for name in ("path", "danmaku_path", "size", "duration",
                         "resolution", "origin", "video_info"):
                if updates[name] is None and name in existing:
                    updates[name] = existing[name]
            payload = self._merge_payload(existing, updates)
            self.conn.execute(
                "INSERT INTO artifacts(artifact_id, session_id, segment_idx, kind,"
                " state, updated_at, data) VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(artifact_id) DO UPDATE SET"
                "   state=excluded.state,"
                "   updated_at=excluded.updated_at,"
                "   data=excluded.data",
                (artifact_id, session_id, segment_idx, str(kind), str(state),
                 now, payload),
            )
            self.conn.commit()
            return self.get_artifact(artifact_id)  # type: ignore[return-value]

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)
            ).fetchone()
            return _row_to_artifact(row) if row else None

    def set_artifact_state(
        self,
        artifact_id: str,
        state: ArtifactState | str,
        *,
        last_error: str | None = None,
        bump_attempts: bool = False,
    ) -> ArtifactRecord | None:
        """更新产物状态并刷新 ``updated_at``（对账的过期判定依赖它）。

        ``last_error`` 与 ``attempts`` 属于载荷，因此这里在已读出的载荷上更新，
        避免整行重写时丢掉其它载荷字段。
        """
        state = ArtifactState(state)
        with self._lock:
            existing = self._raw_payload(artifact_id)
            updates = {"last_error": last_error}
            if bump_attempts:
                updates["attempts"] = int(existing.get("attempts") or 0) + 1
            self.conn.execute(
                "UPDATE artifacts SET state=?, data=?, updated_at=?"
                " WHERE artifact_id=?",
                (str(state), self._merge_payload(existing, updates),
                 _now(), artifact_id),
            )
            self.conn.commit()
            return self.get_artifact(artifact_id)

    def bump_artifact_attempts(self, artifact_id: str) -> None:
        """只累加 ``attempts``，**不改状态**。

        用于"重新驱动处理"：恢复时产物仍应保持 ``recorded``/``rendered``，
        但重试次数要能累加，否则反复重试同一个产物时无从察觉。
        """
        with self._lock:
            existing = self._raw_payload(artifact_id)
            attempts = int(existing.get("attempts") or 0) + 1
            self.conn.execute(
                "UPDATE artifacts SET data=?, updated_at=? WHERE artifact_id=?",
                (self._merge_payload(existing, {"attempts": attempts}),
                 _now(), artifact_id),
            )
            self.conn.commit()

    def set_artifact_path(
        self,
        artifact_id: str,
        *,
        path: str | None = None,
        part_path: str | None = None,
        danmaku_path: str | None = None,
        size: int | None = None,
        duration: float | None = None,
        resolution=None,
    ) -> None:
        """更新产物的文件位置等信息（可选参数沿用旧值，``part_path`` 总是覆盖）。"""
        with self._lock:
            existing = self._raw_payload(artifact_id)
            updates = {
                "path": path if path is not None else existing.get("path"),
                "part_path": part_path,
                "danmaku_path": (danmaku_path if danmaku_path is not None
                                 else existing.get("danmaku_path")),
                "size": size if size is not None else existing.get("size"),
                "duration": (duration if duration is not None
                             else existing.get("duration")),
                "resolution": (resolution if resolution is not None
                               else existing.get("resolution")),
            }
            self.conn.execute(
                "UPDATE artifacts SET data=?, updated_at=? WHERE artifact_id=?",
                (self._merge_payload(existing, updates), _now(), artifact_id),
            )
            self.conn.commit()

    def list_artifacts(
        self,
        *,
        session_id: str | None = None,
        states: Iterable[ArtifactState | str] | None = None,
        terminal: bool | None = None,
    ) -> list[ArtifactRecord]:
        """按场次/状态查询产物。

        ``terminal=False`` 取非终态（对账与内存回收的主要输入）；
        ``terminal=True`` 取终态。
        """
        from .enums import TERMINAL_ARTIFACT_STATES

        clauses: list[str] = []
        params: list[object] = []
        if session_id is not None:
            clauses.append("session_id=?")
            params.append(session_id)
        if states is not None:
            values = [str(ArtifactState(s)) for s in states]
            if not values:
                return []
            clauses.append(f"state IN ({','.join('?' * len(values))})")
            params.extend(values)
        if terminal is not None:
            terminal_values = [str(s) for s in TERMINAL_ARTIFACT_STATES]
            placeholders = ",".join("?" * len(terminal_values))
            if terminal:
                clauses.append(f"state IN ({placeholders})")
            else:
                clauses.append(f"state NOT IN ({placeholders})")
            params.extend(terminal_values)

        sql = "SELECT * FROM artifacts"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY session_id, segment_idx, kind"

        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
            return [_row_to_artifact(r) for r in rows]

    def delete_artifact(self, artifact_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM artifacts WHERE artifact_id=?", (artifact_id,)
            )
            self.conn.commit()

    # --------------------------------------------------------------- 上传组

    def get_or_create_upload_group(
        self,
        group_key: str,
        *,
        taskname: str,
        target: str,
        account: str | None = None,
        engine: str | None = None,
        expires_at: int | None = None,
    ) -> UploadGroupRecord:
        """取上传组；不存在则新建。

        **这是"同组要放到一起"的落地入口**：重启后由 group_key 取回 ``remote_id``
        （bvid），即可把后续分段继续追加到同一稿件，而不是新建稿件。
        """
        with self._lock:
            existing = self.get_upload_group(group_key)
            if existing is not None:
                return existing
            now = _now()
            self.conn.execute(
                "INSERT INTO upload_groups(group_key, taskname, target, account,"
                " engine, remote_id, remote_url, state, created_at, updated_at,"
                " expires_at) VALUES(?,?,?,?,?,NULL,NULL,?,?,?,?)",
                (group_key, taskname, target, account, engine,
                 str(UploadGroupState.OPEN), now, now, expires_at),
            )
            self.conn.commit()
            return self.get_upload_group(group_key)  # type: ignore[return-value]

    def get_upload_group(self, group_key: str) -> UploadGroupRecord | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM upload_groups WHERE group_key=?", (group_key,)
            ).fetchone()
            return _row_to_group(row) if row else None

    def set_upload_group_remote(
        self,
        group_key: str,
        remote_id: str,
        *,
        remote_url: str | None = None,
    ) -> UploadGroupRecord | None:
        """回写远端稿件身份（bvid）。上传成功建稿后必须立即调用。"""
        with self._lock:
            self.conn.execute(
                "UPDATE upload_groups SET remote_id=?, remote_url=?, updated_at=?"
                " WHERE group_key=?",
                (remote_id, remote_url, _now(), group_key),
            )
            self.conn.commit()
            return self.get_upload_group(group_key)

    def touch_upload_group(self, group_key: str) -> None:
        """刷新上传组活跃时间。

        ``updated_at`` 是**空闲过期**的计时基准：只要有新分段入组就刷新，
        因此持续更新的月度合集不会因"创建时间久远"而被判过期。
        """
        with self._lock:
            self.conn.execute(
                "UPDATE upload_groups SET updated_at=? WHERE group_key=?",
                (_now(), group_key),
            )
            self.conn.commit()

    def set_upload_group_state(
        self, group_key: str, state: UploadGroupState | str
    ) -> UploadGroupRecord | None:
        """``sealed`` = 不再向该稿件追加内容。"""
        state = UploadGroupState(state)
        with self._lock:
            self.conn.execute(
                "UPDATE upload_groups SET state=?, updated_at=? WHERE group_key=?",
                (str(state), _now(), group_key),
            )
            self.conn.commit()
            return self.get_upload_group(group_key)

    def list_upload_groups(
        self, taskname: str | None = None
    ) -> list[UploadGroupRecord]:
        with self._lock:
            if taskname is None:
                rows = self.conn.execute(
                    "SELECT * FROM upload_groups ORDER BY created_at"
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM upload_groups WHERE taskname=? ORDER BY created_at",
                    (taskname,),
                ).fetchall()
            return [_row_to_group(r) for r in rows]

    # ------------------------------------------------------------------ 杂项

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value)
            )
            self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            return row["value"] if row else default
