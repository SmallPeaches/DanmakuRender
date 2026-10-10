"""模式迁移与 JSON 载荷的测试。

两部分：

1. **v1 → v2 迁移**：v1 把产物的每个字段都建成一列；v2 把它们收进 JSON ``data`` 列，
   以便 Artifact 后续扩展无需改表。老库必须能无损升级。
2. **载荷容错**：坏 JSON / 缺键 / 类型不符都不能让程序无法启动。
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from DMR.state import (
    SCHEMA_VERSION,
    ArtifactKind,
    ArtifactState,
    StateRepository,
)
from DMR.state.payload import MUTABLE_PAYLOAD_FIELDS, decode_payload, encode_payload
from unit_tests.support import DMRTestCase

_V1_ARTIFACTS_DDL = """
CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY, taskname TEXT NOT NULL, group_id TEXT,
    platform TEXT, room_id TEXT, room_url TEXT, streamer_name TEXT,
    streamer_uid TEXT, title TEXT, started_at INTEGER NOT NULL,
    ended_at INTEGER, updated_at INTEGER NOT NULL
);
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    segment_idx INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    state       TEXT NOT NULL,
    path        TEXT,
    part_path   TEXT,
    danmaku_path TEXT,
    size        INTEGER,
    duration    REAL,
    resolution  TEXT,
    origin      TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    updated_at  INTEGER NOT NULL,
    UNIQUE(session_id, segment_idx, kind)
);
CREATE TABLE upload_groups (
    group_key TEXT PRIMARY KEY, taskname TEXT NOT NULL, target TEXT NOT NULL,
    account TEXT, engine TEXT, remote_id TEXT, remote_url TEXT,
    state TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
    expires_at INTEGER
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _make_v1_db(path: str) -> None:
    """手工建一个 v1 库并写入一条产物（含全部字段）。"""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_V1_ARTIFACTS_DDL)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES(1, 0)")
        conn.execute(
            "INSERT INTO sessions(session_id, taskname, started_at, updated_at)"
            " VALUES('sess-1', 'mytask', 100, 100)")
        conn.execute(
            "INSERT INTO artifacts(artifact_id, session_id, segment_idx, kind, state,"
            " path, part_path, danmaku_path, size, duration, resolution, origin,"
            " attempts, last_error, updated_at)"
            " VALUES('a1', 'sess-1', 1, 'src_video', 'recorded',"
            " 'seg1.flv', NULL, 'seg1.ass', 1024, 600.5, '1920x1080',"
            " 'sess-1:1:src_video_pre', 2, 'oops', 999)")
        conn.commit()
    finally:
        conn.close()


class _MigrationTestCase(DMRTestCase):

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "dmr_state.db")


class TestV1ToV2Migration(_MigrationTestCase):

    def test_version_is_upgraded(self):
        _make_v1_db(self.db_path)
        with StateRepository(self.db_path).open() as repo:
            self.assertEqual(repo.schema_version, SCHEMA_VERSION)

    def test_all_values_are_preserved(self):
        """迁移后产物的每个字段都必须原样保留（尤其是各类类型）。"""
        _make_v1_db(self.db_path)

        with StateRepository(self.db_path).open() as repo:
            artifact = repo.get_artifact('a1')

        self.assertEqual(artifact.artifact_id, 'a1')
        self.assertEqual(artifact.session_id, 'sess-1')
        self.assertEqual(artifact.segment_idx, 1)
        self.assertEqual(artifact.kind, ArtifactKind.SOURCE)
        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertEqual(artifact.path, 'seg1.flv')
        self.assertIsNone(artifact.part_path)
        self.assertEqual(artifact.danmaku_path, 'seg1.ass')
        self.assertEqual(artifact.size, 1024)
        self.assertAlmostEqual(artifact.duration, 600.5)
        self.assertEqual(artifact.resolution, (1920, 1080), "分辨率应还原为元组")
        self.assertEqual(artifact.origin, 'sess-1:1:src_video_pre')
        self.assertEqual(artifact.attempts, 2)
        self.assertEqual(artifact.last_error, 'oops')
        self.assertEqual(artifact.updated_at, 999)

    def test_old_columns_are_dropped(self):
        """迁移后老列应被移除，避免"列与 JSON 双份真相"。"""
        _make_v1_db(self.db_path)

        with StateRepository(self.db_path).open() as repo:
            columns = [row[1] for row in
                       repo.conn.execute("PRAGMA table_info(artifacts)")]

        self.assertIn('data', columns)
        for dropped in ('path', 'part_path', 'danmaku_path', 'size', 'duration',
                        'resolution', 'origin', 'attempts', 'last_error'):
            self.assertNotIn(dropped, columns, f"{dropped} 应已被移除")

    def test_migrated_and_fresh_schema_agree(self):
        """升级得到的库与全新建的库，artifacts 结构与内容形态应一致。"""
        _make_v1_db(self.db_path)
        with StateRepository(self.db_path).open() as repo:
            migrated = [row[1] for row in
                        repo.conn.execute("PRAGMA table_info(artifacts)")]

        fresh_path = os.path.join(self._tmp.name, "fresh.db")
        with StateRepository(fresh_path).open() as repo:
            fresh = [row[1] for row in
                     repo.conn.execute("PRAGMA table_info(artifacts)")]

        self.assertEqual(migrated, fresh)

    def test_migrated_db_is_writable(self):
        """迁移后可正常写入与更新（含载荷字段）。"""
        _make_v1_db(self.db_path)

        with StateRepository(self.db_path).open() as repo:
            repo.set_artifact_state('a1', ArtifactState.UPLOADED,
                                    last_error='done', bump_attempts=True)
            repo.upsert_artifact('a2', 'sess-1', 2, ArtifactKind.SOURCE,
                                 ArtifactState.RECORDED, path='seg2.flv',
                                 size=2048, resolution=(1280, 720))
            first = repo.get_artifact('a1')
            second = repo.get_artifact('a2')

        self.assertEqual(first.state, ArtifactState.UPLOADED)
        self.assertEqual(first.attempts, 3, "attempts 应在原值上 +1")
        self.assertEqual(first.last_error, 'done')
        self.assertEqual(first.path, 'seg1.flv', "更新状态不应丢掉载荷字段")
        self.assertEqual(second.resolution, (1280, 720))


class TestPayloadEncoding(DMRTestCase):
    """载荷编解码本身的行为。"""

    def test_round_trip_through_record(self):
        from DMR.state.repository import ArtifactRecord

        record = ArtifactRecord(
            artifact_id='a1', session_id='s1', segment_idx=1,
            kind=ArtifactKind.SOURCE, state=ArtifactState.RECORDED,
            updated_at=1, path='x.flv', part_path=None, danmaku_path='x.ass',
            size=10, duration=1.5, resolution=(1920, 1080), origin='o',
            attempts=1, last_error=None,
        )
        payload = encode_payload(record)
        decoded = decode_payload(payload)

        self.assertEqual(decoded['path'], 'x.flv')
        self.assertEqual(decoded['resolution'], (1920, 1080))
        self.assertEqual(set(decoded), set(MUTABLE_PAYLOAD_FIELDS))

    def test_decode_null_and_empty(self):
        self.assertEqual(decode_payload(None), {})
        self.assertEqual(decode_payload(""), {})

    def test_decode_malformed_json_is_tolerated(self):
        """坏 JSON 不得抛异常 —— 否则状态库一旦被改坏程序就起不来。"""
        self.assertEqual(decode_payload("{not json"), {})
        self.assertEqual(decode_payload("[1, 2, 3]"), {}, "非对象应视为空载荷")

    def test_decode_accepts_bytes(self):
        self.assertEqual(decode_payload(b'{"path": "x.flv"}')['path'], 'x.flv')

    def test_decode_missing_keys_leaves_defaults_to_caller(self):
        """旧载荷缺少新字段时不应报错（字段扩展的兼容性保证）。"""
        decoded = decode_payload('{"path": "x.flv"}')
        self.assertEqual(decoded, {'path': 'x.flv'})

    def test_decode_bad_resolution_becomes_none(self):
        self.assertIsNone(decode_payload('{"resolution": "garbage"}')['resolution'])
        self.assertEqual(decode_payload('{"resolution": [1280, 720]}')['resolution'],
                         (1280, 720))


class TestPayloadReadTolerance(DMRTestCase):
    """经由仓储读取时的容错（坏数据不能让程序无法启动）。"""

    def setUp(self) -> None:
        super().setUp()
        self.repo = StateRepository(":memory:").open()
        self.addCleanup(self.repo.close)
        self.repo.create_session('s1', 'mytask')

    def test_garbage_payload_reads_as_defaults(self):
        self.repo.upsert_artifact('a1', 's1', 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED, path='x.flv')
        self.repo.conn.execute(
            "UPDATE artifacts SET data='not-json' WHERE artifact_id='a1'")
        self.repo.conn.commit()

        artifact = self.repo.get_artifact('a1')

        self.assertEqual(artifact.state, ArtifactState.RECORDED)
        self.assertIsNone(artifact.path, "坏载荷应退化为默认值而非崩溃")

    def test_payload_with_unknown_extra_key_is_ignored(self):
        """手工往载荷里塞未知键不应让读取失败（向前兼容）。"""
        self.repo.upsert_artifact('a1', 's1', 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED, path='x.flv')
        self.repo.conn.execute(
            "UPDATE artifacts SET data=? WHERE artifact_id='a1'",
            (json.dumps({'path': 'x.flv', 'future_field': 123}),))
        self.repo.conn.commit()

        artifact = self.repo.get_artifact('a1')

        self.assertEqual(artifact.path, 'x.flv')

    def test_unknown_extra_key_is_dropped_on_write(self):
        """写入时应剔除载荷之外的键，避免脏数据长期堆积。

        断言解析后的键集合（而不是原始字符串）：格式变化不应让用例失败，
        但键集合是契约。
        """
        self.repo.upsert_artifact('a1', 's1', 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED, path='x.flv')
        self.repo.conn.execute(
            "UPDATE artifacts SET data=? WHERE artifact_id='a1'",
            (json.dumps({'path': 'x.flv', 'future_field': 123}),))
        self.repo.conn.commit()

        self.repo.set_artifact_state('a1', ArtifactState.UPLOADED)

        raw = self.repo.conn.execute(
            "SELECT data FROM artifacts WHERE artifact_id='a1'").fetchone()[0]
        stored = json.loads(raw)
        self.assertNotIn('future_field', stored, "未知键应被剔除")
        self.assertEqual(stored['path'], 'x.flv', "已知字段必须保留")
        self.assertLessEqual(set(stored), set(MUTABLE_PAYLOAD_FIELDS),
                             "载荷不得含未知键")
        self.assertIn('last_error', stored, "本次写入的字段应在载荷里")

    def test_payload_has_no_unknown_keys_after_partial_update(self):
        """部分更新（只改状态）后，载荷里仍只能有已知键。"""
        self.repo.upsert_artifact('a1', 's1', 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED, path='x.flv')
        self.repo.conn.execute(
            "UPDATE artifacts SET data=? WHERE artifact_id='a1'",
            (json.dumps({'path': 'x.flv', 'junk': 'y'}),))
        self.repo.conn.commit()

        self.repo.set_artifact_state('a1', ArtifactState.UPLOADED)
        stored = json.loads(self.repo.conn.execute(
            "SELECT data FROM artifacts WHERE artifact_id='a1'").fetchone()[0])

        self.assertNotIn('junk', stored)
        self.assertEqual(stored['path'], 'x.flv')
        self.assertEqual(stored['last_error'], None)

    def test_missing_keys_fall_back_to_defaults(self):
        """载荷缺键时读回应得到完整记录（缺键由 dataclass 默认值补齐）。"""
        self.repo.upsert_artifact('a1', 's1', 1, ArtifactKind.SOURCE,
                                  ArtifactState.RECORDED, path='x.flv')
        # 只保留 path，模拟旧版本写入的精简载荷
        self.repo.conn.execute(
            "UPDATE artifacts SET data=? WHERE artifact_id='a1'",
            (json.dumps({'path': 'x.flv'}),))
        self.repo.conn.commit()

        artifact = self.repo.get_artifact('a1')

        self.assertEqual(artifact.path, 'x.flv')
        self.assertIsNone(artifact.danmaku_path, "缺键应回落到默认值")
        self.assertIsNone(artifact.resolution)
        self.assertEqual(artifact.attempts, 0)


if __name__ == "__main__":
    unittest.main()
