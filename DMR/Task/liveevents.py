import logging
import os
import time
from .baseevents import BaseEvents
from ..state import (
    ArtifactKind,
    ArtifactState,
    is_recovered_file_usable,
    make_artifact_key,
    rebuild_video_info,
)
from ..utils import *

#: 内存状态槽位（``state_dict`` 的 ``vtype``）到持久化产物种类的映射。
#: 槽位名沿用 ``VideoInfo.dtype`` 的历史命名，产物种类则是持久化层的枚举。
_VTYPE_TO_KIND = {
    'src_video': ArtifactKind.SOURCE,
    'src_video_pre': ArtifactKind.SOURCE_PRE,
    'dm_video': ArtifactKind.DANMAKU_VIDEO,
}

#: 持久化产物种类到内存状态槽位的反查（恢复时用）
_KIND_TO_VTYPE = {kind: vtype for vtype, kind in _VTYPE_TO_KIND.items()}

#: 内存状态到持久化状态的映射。``None``（槽位已预置但尚未产生产物）不写入 ——
#: 已登记的 ``RECORDED`` 不应被"尚未处理"覆盖。
_STATUS_TO_STATE = {
    'ready': ArtifactState.RECORDED,
    'rendering': ArtifactState.RENDERING,
    'uploading': ArtifactState.UPLOADING,
    'uploaded': ArtifactState.UPLOADED,
    'cleaned': ArtifactState.CLEANED,
}


class LiveEvents(BaseEvents):
    def __init__(self, name, config):
        super().__init__(name, config)
        self.state_dict = {}
        self.ended_dict = {}
        self.logger = logging.getLogger(__name__)
        # 状态持久化（P1）：由 DanmakuRender 注入；缺省时全部同步操作自动跳过。
        # 现有 state_dict 仍是运行时真相，这里只做镜像写入。
        self.state_repo = config.get('state_repo') if isinstance(config, dict) else None
        #: 已创建过占位场次的 group_id（渲染/上传可能先于录制登记发生）
        self._sessions_ensured: set = set()

    @property
    def event_dict(self):
        return {
            'ready': self.onReady,
            'exit': self.onExit,
            'downloader/livestart': self.defaultEvent, 
            'downloader/livesegment': self.onLiveSegment,
            'downloader/liveend': self.onLiveEnd,
            'downloader/livestop': self.onLiveEnd,
            'render/end': self.onRenderEnd,
            'render/error': self.defaultEvent,
            'uploader/end': self.onUploadEnd,
            'uploader/error': self.defaultEvent,
            'cleaner/end': self.defaultEvent,
            'cleaner/error': self.defaultEvent,
            'default': self.defaultEvent,
        }
    
    def defaultEvent(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}')

    # ------------------------------------------------------------------ 状态持久化
    #
    # 原则：``state_dict`` 仍是运行时真相，这里只把**关键状态变化**镜像到状态库，
    # 使进程重启后能知道"哪些分段还没渲染/上传/清理"。所有同步失败都只记日志，
    # 绝不影响录制与上传本身。

    def _ensure_session(self, group_id: str) -> bool:
        """确保状态库中有该场次的记录；成功返回 True。

        渲染/上传可能先于录制登记发生（例如手工触发、或库里没有该场次），
        因此这里按需补一条最小场次记录。
        """
        if self.state_repo is None or not group_id:
            return False
        if group_id in self._sessions_ensured:
            return True
        try:
            self.state_repo.create_session(
                group_id, self.name,
                # 录制侧已登记时会保留其写入的元信息（create_session 幂等）
                title=None,
            )
            self._sessions_ensured.add(group_id)
            return True
        except Exception as e:
            self.logger.warning(f'确保场次 {group_id} 存在失败：{e}')
            return False

    def _sync_artifact(self, group_id: str, vtype: str, segment_idx: int,
                       *, path=None, state=None, origin=None) -> None:
        """把某个槽位的状态镜像到状态库。

        - ``state=None`` 时按当前内存状态推导；仍推导不出（``None``）则**不写入**，
          避免把已登记的 ``RECORDED`` 覆盖成"尚未处理"。
        - 产物不存在时按需补建（kind 由 ``vtype`` 映射），保证后续状态能挂上去。
        """
        kind = _VTYPE_TO_KIND.get(vtype)
        if kind is None or self.state_repo is None:
            return
        try:
            if state is None:
                if not isinstance(segment_idx, int) or segment_idx < 0:
                    return
                info = self._lookup_state(group_id, segment_idx, vtype)
                if not info:
                    return
                raw_status = info.get('status')
                state = _STATUS_TO_STATE.get(raw_status)
                path = path if path is not None else info.get('file')
                if path is None and info.get('file') is not None:
                    path = getattr(info.get('file'), 'path', None)
            if state is None:
                return
            if not self._ensure_session(group_id):
                return

            key = make_artifact_key(group_id, kind, segment_idx)
            file_obj = None
            if path is not None and not isinstance(path, str):
                file_obj = path
                path = getattr(path, 'path', None)

            if self.state_repo.get_artifact(key) is None:
                self.state_repo.upsert_artifact(
                    key, group_id, segment_idx, kind, state,
                    path=path, origin=origin,
                )
            else:
                # 产物已存在（例如下载器已登记 SOURCE）→ 只更新状态与路径。
                # 路径必须一并更新：渲染/转码完成后成品路径会变，
                # 只写状态会留下一个指向旧文件的记录。
                self.state_repo.set_artifact_state(key, state)
                if path is not None:
                    self.state_repo.set_artifact_path(key, path=path)
            if file_obj is not None:
                self.state_repo.set_artifact_path(
                    key, danmaku_path=getattr(file_obj, 'dm_file_id', None),
                )
        except Exception as e:
            self.logger.warning(f'同步产物状态失败（{group_id}/{vtype}）：{e}')

    def _lookup_state(self, group_id: str, segment_idx: int, vtype: str):
        """按"第几个分段 + 槽位"取内存状态。

        ``segment_idx`` 从 1 开始（与 ``VideoInfo.segment_id`` 一致），而
        ``state_dict[group]`` 是追加式列表，因此下标为 ``segment_idx - 1``。
        """
        states = self.state_dict.get(group_id)
        if not states:
            return None
        index = segment_idx - 1
        if 0 <= index < len(states):
            return states[index].get(vtype)
        return None

    def _sync_upload_group(self, group_key: str, upload_args: dict) -> None:
        """把上传组的最小信息落到状态库。

        ``remote_id``（bvid）由上传器在上传成功后回写，这里只保证组记录存在并刷新
        活跃时间 —— 上传组的过期判定基于空闲时间，而不是创建时间。
        """
        if self.state_repo is None or not group_key:
            return
        try:
            self.state_repo.get_or_create_upload_group(
                group_key, taskname=self.name,
                target=upload_args.get('target', 'bilibili'),
                account=upload_args.get('account'),
                engine=upload_args.get('engine'),
            )
            self.state_repo.touch_upload_group(group_key)
        except Exception as e:
            self.logger.warning(f'同步上传组失败（{group_key}）：{e}')

    # ------------------------------------------------------------------ 恢复重驱动

    def resume_recovered(self, artifacts) -> list:
        """把对账收集出的"已录制/已渲染但未完成处理"的产物**重新送回处理链**。

        为什么需要它：``reconcile()`` 只把状态修正到"与磁盘一致"，不会重新驱动。
        若只对账不重跑，重启后那些已录完的分段就会永远停在库里 —— 服务器上观察到的
        "正在录制文件未改名也未上传"正是这个缺口。

        做法是把它们按**原场次**（``session_id``）还原成 ``state_dict`` 的分段状态，
        状态设为 ``ready``，然后交给既有的 ``_check_for_upload`` 走同一条渲染/上传/
        清理路径 —— 不另写一套流程，避免两条路径行为漂移。

        :param artifacts: :class:`~DMR.state.ResumableAction` 序列（已按任务过滤）。
        :returns: 需要发给渲染/上传插件或清扫器的事件消息列表。
        """
        if self.state_repo is None or not artifacts:
            return []

        sessions = self._sessions_by_id()
        messages = []
        touched_groups = []

        for item in artifacts:
            session = sessions.get(item.session_id)
            artifact = self.state_repo.get_artifact(item.artifact_id)
            if artifact is None:
                self.logger.warning(f'待恢复产物 {item.artifact_id} 已不存在，跳过。')
                continue
            try:
                # 传 item.path 作为兜底：载荷若损坏，artifact.path 也会一起丢失，
                # 而对账报告里的路径仍然可信。
                video = rebuild_video_info(artifact, session, path=item.path)
            except Exception as e:
                self.logger.warning(f'重建产物 {item.artifact_id} 失败，跳过：{e}')
                continue
            if video is None:
                self.logger.warning(
                    f'产物 {item.artifact_id} 缺少可用路径，无法恢复处理。')
                continue
            # 判定"这个文件值不值得继续处理"**不依赖 ffprobe**：
            #   1. 文件名以 [正在录制] 开头 → 引擎确实开始录了（正是被杀时留下
            #      的那种文件）；已改名的文件同样正常。
            #   2. 大小达到阈值（默认 30MB）→ 录到了实质内容。
            # 探测时长既贵又会把"环境里没装 ffprobe"误判成"文件坏了"，
            # 因此这里用确定的信号判断。
            if not is_recovered_file_usable(
                    getattr(video, 'path', None),
                    getattr(video, 'size', None) or artifact.size,
                    min_size_mb=self._min_valid_size_mb()):
                self._handle_unusable(artifact, item)
                continue

            index = item.segment_idx - 1
            if index < 0:
                self.logger.warning(f'产物 {item.artifact_id} 的分段序号非法，跳过。')
                continue
            # 录制中途被杀时，文件还叫 ``[正在录制]...Part000...``（引擎只在"下一个
            # 分段开始时"才把上一段改名）。恢复时补上这次改名，让它与正常流程一致。
            video = self._promote_intermediate_name(video, item)
            group = self.state_dict.setdefault(item.session_id, [])
            while len(group) <= index:
                group.append(self._blank_segment_state())
            vtype = _KIND_TO_VTYPE.get(artifact.kind, 'src_video')
            group[index][vtype].update({'status': 'ready', 'file': video})
            if item.session_id not in touched_groups:
                touched_groups.append(item.session_id)

        for group_id in touched_groups:
            self.logger.info(f'恢复 {len(self.state_dict[group_id])} 个分段待处理（{group_id}）。')
            # 录制侧已结束的场次按"已结束"处理：这样非实时上传（整组一次性上传）
            # 也会被触发，与 onLiveEnd 的行为保持一致。
            if self._session_has_ended(group_id):
                self.ended_dict[group_id] = time.time()
            if self.config['common_event_args'].get('auto_upload'):
                messages += self._check_for_upload(group_id)

        if messages:
            self.logger.info(f'已重新派发 {len(messages)} 个处理任务（渲染/上传）。')
        return messages

    def _promote_intermediate_name(self, video, item) -> object:
        """把 ``[正在录制]`` 中间名改成最终文件名（与录制完成时同样的命名规则）。

        为什么需要：分段式下载引擎（ffmpeg / streamlink / streamgears）先写
        ``[正在录制]<task>-<时间>-Part%03d-<uuid>.<ext>``，**只在下一个分段开始时**
        才由 ``segment_callback`` 改用 ``download_args.output_name`` 模板改名。
        进程若在那之前退出，文件就永远停在中间名上。

        失败一律不改路径：**能上传比名字漂亮重要**，不能因为改名失败就丢掉产物。
        """
        path = getattr(video, 'path', None)
        if not path or not os.path.exists(path):
            return video
        if os.path.basename(path).find('[正在录制]') < 0:
            return video   # 名字已是最终的（文件下载类引擎本来就这样）

        try:
            renamed = self._compute_output_path(video)
        except Exception as e:
            self.logger.warning(f'计算产物 {item.artifact_id} 的最终文件名失败：{e}')
            return video
        if not renamed or renamed == path:
            return video

        new_path = rename_safe(path, renamed)
        if not new_path:
            self.logger.warning(
                f'产物 {item.artifact_id} 改名失败（目标 {renamed} 可能已存在），'
                f'继续使用原名：{path}')
            return video

        self.logger.info(f'产物 {item.artifact_id} 已改名为 {new_path}。')
        video.path = new_path
        # 同步回状态库：否则下次重启又会按旧路径找不到文件
        try:
            self.state_repo.set_artifact_path(item.artifact_id, path=new_path,
                                              part_path=None)
        except Exception as e:
            self.logger.warning(f'回写产物 {item.artifact_id} 的新路径失败：{e}')
        return video

    def _min_valid_size_mb(self) -> float:
        """判定"录到一半的文件是否可信"的大小阈值（``recovery.min_valid_size_mb``）。

        与启动对账校验中断产物用的是**同一个**配置项：两者都在回答
        "这个文件是否已录到实质内容"。
        """
        try:
            from ..state import RecoveryConfig

            return float(RecoveryConfig.from_mapping(
                self.config.get('recovery')).min_valid_size_mb)
        except Exception as e:
            self.logger.warning(f'读取 recovery.min_valid_size_mb 失败：{e}')
            return 30.0

    def _handle_unusable(self, artifact, item) -> None:
        """处置"大小不足以继续处理"的产物（文件太小，或文件已不存在）。

        策略来自 ``recovery.on_unusable_file``：

        - ``skip``（默认）：标记 ``skipped`` 并停止重试，**不删除文件**
        - ``discard``       ：同上并**删除文件**
        - ``ask``           ：保持原状态，每次重启都会再试一遍

        标记为 ``skipped`` 的意义在于它属于**终态** —— 不会被
        ``collect_resumable`` 再次选中，因此不会每次重启都白试一遍、也不会把日志
        刷满重复告警。
        """
        from ..state import RecoveryConfig, UnusableFileAction

        try:
            action = RecoveryConfig.from_mapping(
                self.config.get('recovery')).on_unusable_file
        except Exception as e:
            self.logger.warning(f'读取 recovery.on_unusable_file 失败：{e}')
            action = UnusableFileAction.SKIP

        path = getattr(artifact, "path", None)
        size = getattr(artifact, "size", None)
        threshold = self._min_valid_size_mb()
        if size is None:
            reason = f'文件大小未知，无法确认达到 {threshold:.0f}MB 阈值'
        elif not os.path.exists(path or ""):
            reason = '文件已不存在'
        else:
            reason = (f'文件仅 {size / 1024 / 1024:.1f}MB，'
                      f'低于 {threshold:.0f}MB 阈值')

        # 内存状态标记为 skipped：防止本次运行内被再次派发
        index = item.segment_idx - 1
        group = self.state_dict.get(item.session_id) or []
        if 0 <= index < len(group):
            vtype = _KIND_TO_VTYPE.get(artifact.kind, 'src_video')
            group[index][vtype]['status'] = 'skipped'

        if action is UnusableFileAction.ASK:
            self.logger.warning(
                f'产物 {item.artifact_id} 不满足恢复条件（{reason}），'
                f'按 recovery.on_unusable_file=ask 保持原状态，未做处理。')
            return

        if action is UnusableFileAction.DISCARD and path:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    reason += '，已按配置删除'
            except OSError as e:
                self.logger.warning(f'删除不可用产物 {path} 失败：{e}')
        try:
            self.state_repo.set_artifact_state(
                item.artifact_id, ArtifactState.SKIPPED, last_error=reason)
        except Exception as e:
            self.logger.warning(f'标记产物 {item.artifact_id} 为 skipped 失败：{e}')
        self.logger.warning(
            f'产物 {item.artifact_id} 不满足恢复条件（{reason}），'
            f'已标记为 skipped，不再重试。')

    def _compute_output_path(self, video) -> str | None:
        """按 ``download_args`` 的命名规则算出该产物的最终路径。

        规则与 ``stream_downloader.segment_callback`` 保持一致：模板取自
        ``output_name``，目录取自 ``output_dir``，扩展名取自 ``output_format``。
        """
        download_args = self.config.get('download_args') or {}
        output_dir = download_args.get('output_dir')
        if not output_dir:
            # 没配输出目录时，产物就在原目录旁边
            output_dir = os.path.dirname(getattr(video, 'path', '') or '') or None
        if not output_dir:
            return None

        template = download_args.get('output_name')
        if template:
            stem = replace_keywords(template, video, replace_invalid=True)
            stem = stem[:int(download_args.get('max_fn_length') or 80)]
        else:
            # 与 segment_callback 的兜底一致：沿用原主名
            stem = os.path.splitext(os.path.basename(video.path))[0]
            stem = stem.replace('[正在录制]', '')
        output_format = download_args.get('output_format') or \
            os.path.splitext(video.path)[1].lstrip('.')
        return os.path.join(output_dir, f'{stem}.{output_format}')

    def _sessions_by_id(self) -> dict:
        """读取状态库中的场次，按 ``session_id`` 建索引（失败时返回空表）。"""
        try:
            return {s.session_id: s for s in self.state_repo.list_sessions()}
        except Exception as e:
            self.logger.warning(f'读取场次记录失败，恢复时将只有产物字段可用：{e}')
            return {}

    def _session_has_ended(self, group_id: str) -> bool:
        try:
            session = self.state_repo.get_session(group_id)
        except Exception as e:
            self.logger.warning(f'读取场次 {group_id} 失败：{e}')
            return False
        return bool(session is not None and session.is_ended)

    @staticmethod
    def _blank_segment_state() -> dict:
        """一个分段的内存状态骨架（与 onLiveSegment 的初值一致）。"""
        return {
            'src_video': {'status': None, 'file': None, 'wait': []},
            'src_video_pre': {'status': None, 'file': None, 'wait': []},
            'dm_video': {'status': None, 'file': None, 'wait': []},
        }

    def onReady(self, *args, **kwargs):
        return PipeMessage(
            source=self.name,
            target='downloader',
            event='newtask',
            data={
                'dltype': self.config['download_args']['dltype'],
                'taskname': self.name,
                'config': self.config['download_args'],
            }
        )
    
    def onLiveSegment(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}')
        video:VideoInfo = message.data
        video_state = self._blank_segment_state()
        if self.state_dict.get(video.group_id):
            self.state_dict[video.group_id].append(video_state)
        else:
            self.state_dict[video.group_id] = [video_state]

        # 分段已落盘：把源视频登记为 RECORDED（并补上弹幕附属文件）。
        # 下载器通常已登记过，这里是幂等补充（例如虚拟下载/视频下载等不经过下载器分段的路径）。
        self._sync_artifact(video.group_id, 'src_video', video.segment_id,
                            path=video, state=ArtifactState.RECORDED)

        ret_msgs = []
        if self.config['common_event_args'].get('auto_transcode'):
            transcode_args = self.config['render_args']['transcode']
            if transcode_args.get('output_name'):
                filename = replace_keywords(transcode_args['output_name'], video, replace_invalid=True) + \
                        f".{transcode_args.get('format','mp4')}"
            else:
                filename = os.path.splitext(os.path.basename(video.path))[0] + \
                        f"（转码后）.{transcode_args.get('format','mp4')}"
            if transcode_args.get('output_dir'):
                output_dir = transcode_args.get('output_dir')
            else:
                output_dir = os.path.dirname(video.path) + '（转码后）'
            output = os.path.join(output_dir, filename)
            transcode_msg = PipeMessage(
                source=self.name,
                target='render',
                event='newtask',
                request_id=uuid(),
                data={
                    'taskname': self.name,
                    'mode': 'transcode',
                    'video': video,
                    'output': output,
                    'args': transcode_args,
                }
            )
            self.state_dict[video.group_id][-1]['src_video_pre'].update({'status': 'ready', 'file': video})
            self.state_dict[video.group_id][-1]['src_video']['status'] = 'rendering'
            self.state_dict[video.group_id][-1]['src_video']['wait'].append(transcode_msg.request_id)
            # 产物语义是"替代"：src_video_pre 是转码前的原始录制流，src_video 是转码结果。
            self._sync_artifact(video.group_id, 'src_video_pre', video.segment_id,
                                path=video, state=ArtifactState.RECORDED)
            self._sync_artifact(video.group_id, 'src_video', video.segment_id,
                                state=ArtifactState.RENDERING)
            ret_msgs.append(transcode_msg)
        else:
            self.state_dict[video.group_id][-1]['src_video'].update({'status': 'ready', 'file': video})
        
        if self.config['common_event_args'].get('auto_render'):
            render_args = self.config['render_args']['dmrender']
            if render_args.get('output_name'):
                filename = replace_keywords(render_args['output_name'], video, replace_invalid=True) + \
                        f".{render_args.get('format','mp4')}"
            else:
                filename = os.path.splitext(os.path.basename(video.path))[0] + \
                        f"（弹幕版）.{render_args.get('format','mp4')}"
            if render_args.get('output_dir'):
                output_dir = render_args.get('output_dir')
            else:
                output_dir = os.path.dirname(video.path) + '（弹幕版）'
            output = os.path.join(output_dir, filename)
            render_msg = PipeMessage(
                source=self.name,
                target='render',
                event='newtask',
                request_id=uuid(),
                data={
                    'taskname': self.name,
                    'mode': 'dmrender',
                    'video': video,
                    'output': output,
                    'args': render_args,
                }
            )
            self.state_dict[video.group_id][-1]['dm_video']['status'] = 'rendering'
            self.state_dict[video.group_id][-1]['dm_video']['wait'].append(render_msg.request_id)
            # 弹幕版是独立产物，先登记渲染中的目标路径
            self._sync_artifact(video.group_id, 'dm_video', video.segment_id,
                                path=output, state=ArtifactState.RENDERING,
                                origin=video.dm_file_id)
            ret_msgs.append(render_msg)

        if self.config['common_event_args'].get('auto_upload'):
            ret_msgs += self._check_for_upload(video.group_id, len(self.state_dict[video.group_id])-1)
                
        return ret_msgs
    
    def onLiveEnd(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}.')
        group_id = message.data
        if group_id is None:
            return
        
        if group_id in self.state_dict:
            self.ended_dict[group_id] = time.time()
        else:
            self.logger.debug(f'No such group:{group_id}.')
        
        ret_msgs = []
        if self.config['common_event_args'].get('auto_upload'):
            upload_msgs = self._check_for_upload(group_id)
            ret_msgs += upload_msgs

        self._free_state_memory()
        
        return ret_msgs
    
    def _passes_length_gate(self, video, min_length: float, arg: dict) -> bool:
        """判断一个产物是否通过"长度足够"这道门槛（实时与非实时分支共用）。

        规则**不依赖 ffprobe**：

        - **时长已知**：按 ``min_length`` 判断（与原有行为一致）。
        - **时长未知**（恢复出的产物、升级前登记的旧数据、探测失败）：改用
          **文件大小**判断，阈值取 ``recovery.min_valid_size_mb``（默认 30MB）。
          时间长度未知并不代表文件不可用，而大小是"录到实质内容"的直接证据；
          若沿用"未知就跳过"，恢复出来的产物会永远传不上去。
        """
        duration = getattr(video, 'duration', None)
        # 0 与 None 同等看待：对已封闭的录制文件来说"时长 0 秒"只意味着元信息
        # 没写上（或探测失败），不是真实时长。
        if duration:
            if duration < min_length:
                self.logger.info(
                    f'视频{video.path}时长为{duration}s，设置{min_length}s，跳过上传。')
                return False
            return True

        # 时长未知 → 用大小兜底
        min_size_mb = self._min_valid_size_mb()
        size = getattr(video, 'size', None)
        if not size:
            try:
                size = os.path.getsize(video.path)
                video.size = size
            except OSError:
                size = None
        if size is None or size < min_size_mb * 1024 * 1024:
            self.logger.warning(
                f'视频{video.path}的时长未知，且大小不足 {min_size_mb:.0f}MB，'
                f'跳过上传。')
            return False
        self.logger.info(
            f'视频{video.path}的时长未知，按大小 {size / 1024 / 1024:.1f}MB '
            f'判定为可上传。')
        return True

    def _check_for_upload(self, group_id:str, _idx:int=None):
        ret_msgs = []
        if not self.state_dict.get(group_id):
            return ret_msgs
        upload_args = self.config['upload_args']
        for idx, video_state in enumerate(self.state_dict[group_id]):
            if _idx is not None and idx != _idx:
                continue
            for vtype, info in video_state.items():
                if info['status'] != 'ready':
                    continue
                for upload_file_types, upload_arg in upload_args.items():
                    # 判断当前视频是否需要上传
                    if vtype in upload_file_types.split('+'):
                        for upid, arg in enumerate(upload_arg):
                            # 实时上传
                            if not arg.get('realtime'):
                                continue
                            if not self._passes_length_gate(info['file'],
                                                            arg.get('min_length', 0) or 0,
                                                            arg):
                                continue
                            upload_group_id = info['file'].upload_group_id if hasattr(info['file'], 'upload_group_id') else group_id
                            group_key = upload_group_id+'_'+upload_file_types+'_'+str(upid)
                            upload_msg = PipeMessage(
                                source=self.name,
                                target='uploader',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': [info['file']],
                                    'engine': arg['engine'],
                                    'stateless': False,
                                    'upload_group': group_key,
                                    'args': arg,
                                }
                            )
                            self.state_dict[group_id][idx][vtype]['status'] = 'uploading'
                            self.state_dict[group_id][idx][vtype]['wait'].append(upload_msg.request_id)
                            # 状态库：登记上传组（上传器成功后会回写 bvid）并把产物标为上传中。
                            # group_key 与上传器使用的键必须一致，否则 bvid 会落到另一个键上。
                            self._sync_upload_group(group_key, arg)
                            self._sync_artifact(group_id, vtype, idx + 1,
                                                state=ArtifactState.UPLOADING)
                            ret_msgs.append(upload_msg)
        
        # 如果当前视频组已经被标记结束，检查是否有视频组完全准备好上传（用于非实时上传）
        if group_id in self.ended_dict:
            # 遍历所有视频类型
            video_types = list(self.state_dict[group_id][-1].keys())
            for vtype in video_types:
                # 检查是否全部准备上传
                videos = []
                for idx, video_state in enumerate(self.state_dict[group_id]):
                    if video_state[vtype]['status'] == 'ready':
                        videos.append(video_state[vtype]['file'])
                    else:
                        videos = []
                        break
                if not videos:
                    continue

                # 判断当前视频是否需要上传
                for upload_file_types, upload_arg in upload_args.items():
                    if vtype in upload_file_types.split('+'):
                        for upid, arg in enumerate(upload_arg):
                            # 此处只做非实时上传
                            if arg.get('realtime'):
                                continue
                            # 与实时分支同一规则：时长已知按 min_length，
                            # 时长未知改用文件大小判定（不依赖 ffprobe）。
                            min_length = arg.get('min_length', 0) or 0
                            up_videos = [video for video in videos
                                         if self._passes_length_gate(
                                             video, min_length, arg)]
                            if not up_videos:
                                # 所有分段都不达标：跳过而非索引空列表
                                # （原实现直接取 up_videos[0]，会抛 IndexError
                                # 并中断事件处理）
                                continue
                            upload_group_id = up_videos[0].upload_group_id if hasattr(up_videos[0], 'upload_group_id') else group_id
                            group_key = upload_group_id+'_'+upload_file_types+'_'+str(upid)
                            upload_msg = PipeMessage(
                                source=self.name,
                                target='uploader',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': up_videos,
                                    'engine': arg['engine'],
                                    'stateless': True,
                                    'upload_group': group_key,
                                    'args': arg,
                                }
                            )
                            # 标记状态信息
                            for idx, _ in enumerate(self.state_dict[group_id]):
                                self.state_dict[group_id][idx][vtype]['status'] = 'uploading'
                                self.state_dict[group_id][idx][vtype]['wait'].append(upload_msg.request_id)
                                self._sync_artifact(group_id, vtype, idx + 1,
                                                    state=ArtifactState.UPLOADING)
                            self._sync_upload_group(group_key, arg)
                            ret_msgs.append(upload_msg)

        return ret_msgs
    
    def _group_or_none(self, group_id, *, source: str):
        """取某个录制分组的运行时状态；不存在时告警并返回 ``None``。

        **为什么必须判空**：``state_dict`` 会因两种正常情况变空：

        1. 任务被**重启**（配置更新时是"删任务 + 5 秒后重建任务"）——
           `onExit` 清空 ``state_dict``，而**旧任务实例派发出去的渲染/转码/上传任务
           仍在管道里**。它们完成后会把结果发回**任务名**，此时消息由**新的实例**
           处理，而新实例的 ``state_dict`` 是空的。
        2. 分组处理完成后由 :meth:`_free_state_memory` 主动释放。

        这两种情况下"结果到达时分组已不存在"是**预期现象**，不是错误 ——
        丢弃即可，但必须记日志，否则会像"上传成功却记不上账"那样难以定位。
        （生产实测：渲染在任务重启 2 分钟后才回来，直接把监听线程打挂。）
        """
        group = self.state_dict.get(group_id)
        if group is None:
            self.logger.warning(
                f'{self.name}: 收到 {source} 的结果，但分组 {group_id} 已不存在'
                f'（任务可能已被重启或该分组已处理完毕），结果已丢弃。'
            )
        return group

    def onRenderEnd(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}.')
        request_id = message.request_id
        video:VideoInfo = message.data.get('output')
        video_states = self._group_or_none(video.group_id, source='渲染/转码')
        if video_states is None:
            # 返回空列表而非 None：本方法的契约是"要派发的消息列表"，调用方会直接
            # 拼接（``ret_msgs += func(msg)``），返回 None 会抛 TypeError。
            return []
        # 将状态信息中request_id对应的等待移除
        for idx, video_state in enumerate(video_states):
            for vtype, info in video_state.items():
                if request_id in info['wait']:
                    self.state_dict[video.group_id][idx][vtype]['wait'].remove(request_id)
                    if len(self.state_dict[video.group_id][idx][vtype]['wait']) == 0:
                        self.state_dict[video.group_id][idx][vtype]['status'] = 'ready'
                        self.state_dict[video.group_id][idx][vtype]['file'] = video
                        # 渲染/转码完成 → 结果成为该槽位的成品（RENDERED）
                        self._sync_artifact(video.group_id, vtype, idx + 1,
                                            path=video,
                                            state=ArtifactState.RENDERED)
        
        ret_msgs = []
        if self.config['common_event_args'].get('auto_upload'):
            upload_msgs = self._check_for_upload(video.group_id)
            ret_msgs += upload_msgs

        return ret_msgs
    
    def _check_for_clean(self, group_id=None):
        ret_msgs = []
        clean_args = self.config['clean_args']
        for group_id, video_states in self.state_dict.items():
            for idx, video_state in enumerate(video_states):
                for vtype, info in video_state.items():
                    if info['status'] != 'uploaded':
                        continue
                    for clean_file_types, clean_arg in clean_args.items():
                        # 判断当前视频是否需要清理
                        if not (vtype in clean_file_types.split('+') or clean_file_types == 'all'):
                            continue
                        # 只有真正命中了清理规则才标记为 cleaned ——
                        # 原实现的赋值在循环之外，会对**所有**已上传产物无条件置为
                        # cleaned，导致"没清理的文件被当作已清理"而提前释放状态。
                        for arg in clean_arg:
                            files = [info['file']]
                            # 判断是否需要清理源文件
                            if vtype == 'dm_video' and arg.get('w_srcfile', False) == True and video_state['src_video']['file'] is not None:
                                files.append(video_state['src_video']['file'])
                                self.state_dict[group_id][idx]['src_video']['status'] = 'cleaned'
                                self._sync_artifact(group_id, 'src_video', idx + 1,
                                                    state=ArtifactState.CLEANED)
                            # 判断是否需要清理源文件（转码前）
                            if vtype == 'src_video' and arg.get('w_srcpre', True) == True and video_state['src_video_pre']['file'] is not None:
                                files.append(video_state['src_video_pre']['file'])
                                self.state_dict[group_id][idx]['src_video_pre']['status'] = 'cleaned'
                                self._sync_artifact(group_id, 'src_video_pre', idx + 1,
                                                    state=ArtifactState.CLEANED)

                            clean_msg = PipeMessage(
                                source=self.name,
                                target='cleaner',
                                event='newtask',
                                request_id=uuid(),
                                data={
                                    'taskname': self.name,
                                    'files': files,
                                    'method': arg['method'],
                                    'delay': arg['delay'],
                                    'args': arg,
                                }
                            )
                            self.state_dict[group_id][idx][vtype]['status'] = 'cleaned'
                            self._sync_artifact(group_id, vtype, idx + 1,
                                                state=ArtifactState.CLEANED)
                            ret_msgs.append(clean_msg)

        return ret_msgs
    
    def _free_state_memory(self):
        final_status = 'ready'
        if self.config['common_event_args'].get('auto_upload'):
            final_status = 'uploaded'
        if self.config['common_event_args'].get('auto_clean'):
            final_status = 'cleaned'
        
        for group_id in list(self.ended_dict.keys()):
            # ``ended_dict`` 可能含有 ``state_dict`` 里没有的组：
            # ``onLiveEnd`` 在分组不存在时只记 debug 而没有写入 ``ended_dict``，
            # 但恢复流程（``resume_recovered``）会直接写 ``ended_dict``。
            # 直接下标访问会抛 KeyError 并打断监听线程。
            if group_id not in self.state_dict:
                self.ended_dict.pop(group_id, None)
                continue
            need_free = True
            for idx, video_state in enumerate(self.state_dict[group_id]):
                for vtype, info in video_state.items():
                    if info['status'] is not None and info['status'] != final_status:
                        need_free = False
                        break
                if not need_free: break
            if need_free:
                self.logger.debug(f'视频组{group_id}处理完成，视频信息已被释放.')
                self.ended_dict.pop(group_id)
                self.state_dict.pop(group_id)

        for group_id in list(self.ended_dict.keys()):
            if time.time() - self.ended_dict[group_id] > 72*3600:
                self.logger.debug(f'视频组{group_id}处理超时，视频信息将被释放.')
                self.ended_dict.pop(group_id)
                self.state_dict.pop(group_id)

    def onUploadEnd(self, message:PipeMessage):
        self.logger.info(f'{self.name}: {message.msg}.')
        request_id = message.request_id
        # 将状态信息中request_id对应的等待移除
        for group_id, video_states in self.state_dict.items():
            for idx, video_state in enumerate(video_states):
                for vtype, info in video_state.items():
                    if request_id in info['wait']:
                        self.state_dict[group_id][idx][vtype]['wait'].remove(request_id)
                        if len(self.state_dict[group_id][idx][vtype]['wait']) == 0:
                            self.state_dict[group_id][idx][vtype]['status'] = 'uploaded'
                            # 全部待处理请求都结束了 → 该产物确实已进稿件
                            self._sync_artifact(group_id, vtype, idx + 1,
                                                state=ArtifactState.UPLOADED)
        
        ret_msgs = []
        if self.config['common_event_args'].get('auto_clean'):
            clean_msgs = self._check_for_clean()
            ret_msgs += clean_msgs
        
        return ret_msgs

    def onExit(self, *args, **kwargs) -> None:
        self.logger.info(f'{self.name}: 任务结束.')
        self.state_dict.clear()
        self.ended_dict.clear()
        return PipeMessage(
            source=self.name,
            target='downloader',
            event='stoptask',
            data=self.name,
        )
