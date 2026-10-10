import logging
import threading
import queue
import time
import json
from concurrent.futures import ThreadPoolExecutor
from os.path import join, exists
from datetime import datetime
from typing import Tuple

from DMR.utils import VideoInfo, PipeMessage, DateTimeEncoder, DateTimeDecoder, uuid


def _import_engine(module: str, cls: str):
    """惰性导入上传引擎类（避免在模块导入期就加载全部引擎依赖）。"""
    import importlib

    return getattr(importlib.import_module(module, __package__), cls)


#: 引擎名 -> 惰性加载器。集中在此处，新增引擎只需加一行。
_UPLOADER_ENGINES = {
    'biliuprs': lambda: _import_engine('.biliuprs', 'biliuprs'),
    'subprocess': lambda: _import_engine('.subprocess_uploader', 'SubprocessUploader'),
    'youtubev3': lambda: _import_engine('.youtubev3', 'youtubev3'),
    'biliwebapi': lambda: _import_engine('.biliwebapi', 'BiliWebApi'),
}

#: 支持"按远端稿件标识追加/续传"的引擎。
#: - ``biliwebapi``：``resume_bvid`` → 载入既有稿件，新分段作为新分P追加
#: - ``biliuprs``  ：``resume_bvid`` → 使用 ``biliup append --vid <bvid>`` 追加
#: 其余引擎（youtubev3 / subprocess）没有"追加到既有稿件"的概念。
_RESUME_CAPABLE_ENGINES = frozenset({'biliwebapi', 'biliuprs'})


class Uploader():
    def __init__(self,
                 pipe:Tuple[queue.Queue, queue.Queue],
                 nuploaders:int=1,
                 state_repo=None,
                 uploader_factory=None,
                 **kwargs,
                 ) -> None:
        
        self.nuploaders = int(nuploaders)
        self.send_queue, self.recv_queue = pipe
        self.logger = logging.getLogger(__name__)
        self.kwargs = kwargs

        # 状态持久化（P1）：记录每个 upload_group 对应的远端稿件（bvid），
        # 使进程重启后新分段仍追加到同一稿件，而不是新建稿件。
        self.state_repo = state_repo
        # 可注入的构造工厂，便于单测替换掉"需要登录/联网"的上传引擎
        self._uploader_factory = uploader_factory

        self.stoped = True
        self._piperecvprocess = None
        self._uploader_pool = {}
        self.upload_tasks = {}
        self.failed_tasks = {}
        self.failed_tasks_file = '.temp/failed_uploads.json'
        self.load_failed_tasks()
        
        self.upload_executors = ThreadPoolExecutor(max_workers=self.nuploaders)
        self._lock = threading.Lock()

    def load_failed_tasks(self):
        if exists(self.failed_tasks_file):
            try:
                with open(self.failed_tasks_file, 'r', encoding='utf-8') as f:
                    data = json.load(f, cls=DateTimeDecoder)
                    # Restore datetime objects and VideoInfo objects
                    for uuid, task in data.items():
                        if 'files' in task:
                            restored_files = []
                            # Wrap in VideoInfo
                            for f in task['files']:
                                restored_files.append(VideoInfo(**f))
                            task['files'] = restored_files
                            # Also update files in config
                            # if 'config' in task and 'files' in task['config']:
                            #     task['config']['files'] = restored_files
                        self.failed_tasks[uuid] = task
                self.logger.info(f'Loaded {len(self.failed_tasks)} failed upload tasks.')
            except Exception as e:
                self.logger.error(f'Failed to load failed tasks: {e}')

    def save_failed_tasks(self):
        try:
            with open(self.failed_tasks_file, 'w', encoding='utf-8') as f:
                json.dump(self.failed_tasks, f, cls=DateTimeEncoder, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f'Failed to save failed tasks: {e}')

    def retry_task(self, uuid):
        with self._lock:
            if uuid in self.failed_tasks:
                task = self.failed_tasks.pop(uuid)
                self.save_failed_tasks()
                
                # Re-submit
                task['status'] = 'waiting'
                self.upload_tasks[task['uuid']] = task
                if task.get('stream_queue'):
                    threading.Thread(target=self._upload_subprocess, args=(task,), daemon=True).start()
                else:
                    self.upload_executors.submit(self._upload_subprocess, task)
                return True
            return False

    def delete_failed_task(self, uuid):
        with self._lock:
            if uuid in self.failed_tasks:
                self.failed_tasks.pop(uuid)
                self.save_failed_tasks()
                return True
            return False

    def _pipeSend(self, event, msg, target='engine', request_id=None, dtype=None, data=None, **kwargs):
        if self.send_queue:
            msg = PipeMessage(
                source='uploader',
                target=target,
                event=event,
                request_id=request_id,
                msg=msg,
                dtype=dtype,
                data=data,
                **kwargs,
            )
            self.send_queue.put(msg)

    def _pipeRecvMonitor(self):
        while self.stoped == False and self.recv_queue is not None:
            message:PipeMessage = self.recv_queue.get()
            try:
                if message.target == 'uploader':
                    if message.event == 'newtask':
                        self.add_task(message)
            except Exception as e:
                self.logger.error(f'Message:{message} raise an error.')
                self.logger.exception(e)

    def start(self):
        self.stoped = False
        self._piperecvprocess = threading.Thread(target=self._pipeRecvMonitor, daemon=True)
        self._piperecvprocess.start()

    def _free_uploader_pool(self):
        with self._lock:
            for upload_group in list(self._uploader_pool.keys()):
                expire = self._uploader_pool[upload_group]['expire']
                if expire > 0 and time.time() - self._uploader_pool[upload_group]['ctime'] > expire:
                    self._uploader_pool[upload_group]['class'].stop()
                    self._uploader_pool.pop(upload_group)
                    self.logger.debug(f'Uploader {upload_group} expired and removed.')

    def add_task(self, msg:PipeMessage):
        with self._lock:
            config = msg.data
            file = config.get('files')[0]
            stream_queue = None
            if hasattr(file, 'stream_queue') and file.stream_queue is not None:
                stream_queue = file.stream_queue
            task = {
                'uuid': uuid(),
                'source': msg.source,
                'request_id': msg.request_id,
                'upload_group': config.get('upload_group'),
                'engine': config.get('engine', 'biliuprs'),
                'args': config.get('args', {}),
                'files': config.get('files'),
                'stream_queue': stream_queue,
                # 'config': config,
                'status': 'waiting',
            }
            self.upload_tasks[task['uuid']] = task
            if stream_queue:
                threading.Thread(target=self._upload_subprocess, args=(task,), daemon=True).start()
            else:
                self.upload_executors.submit(self._upload_subprocess, task)

    def _get_or_create_uploader(self, task: dict):
        """取出或新建某上传组的上传器实例。

        **状态持久化的关键接点**：实例是按需创建并可在空闲后释放的，因此"同一
        upload_group 属于同一稿件"这件事不能只靠实例的内存状态维系。新建实例时若
        状态库中已记录该组的 ``remote_id``（bvid），就注入给引擎，使其把新的分段
        追加到既有稿件。
        """
        upload_group: str = task['upload_group']
        upload_args = task['args']

        with self._lock:
            if upload_group in self._uploader_pool:
                entry = self._uploader_pool[upload_group]
                entry['ctime'] = time.time()
                return entry['class']

            extra = {}
            remote_id = self._lookup_group_remote_id(upload_group)
            if remote_id and self._supports_resume(task.get('engine')):
                # 复用既有稿件；引擎内部若发现稿件已不存在会自行回退为新建
                extra['resume_bvid'] = remote_id
                self.logger.info(
                    f'上传组 {upload_group} 复用既有稿件 {remote_id}。'
                )

            target_uploader = self._create_uploader(task.get('engine'),
                                                    {**upload_args, **extra})
            self._uploader_pool[upload_group] = {
                'class': target_uploader,
                'ctime': time.time(),
                'expire': task.get('expire', 7*24*3600)
            }
            return target_uploader

    def _create_uploader(self, engine: str, args: dict):
        """构造上传引擎实例。``uploader_factory`` 可注入以替换默认实现。"""
        if self._uploader_factory is not None:
            return self._uploader_factory(engine, args)
        try:
            loader = _UPLOADER_ENGINES[engine]
        except KeyError:
            raise ValueError(f'Unknown engine: {engine}')
        return loader()(**args)

    @staticmethod
    def _supports_resume(engine: str) -> bool:
        """该引擎是否支持"按远端稿件标识续传/追加"。

        目前只有 B 站 Web API 实现了 ``resume_bvid``（把新分P追加到既有稿件）。
        """
        return engine in _RESUME_CAPABLE_ENGINES

    def _lookup_group_remote_id(self, upload_group: str) -> str | None:
        """从状态库读取该上传组的远端稿件标识；无状态库或未记录时返回 None。"""
        if self.state_repo is None:
            return None
        try:
            group = self.state_repo.get_upload_group(upload_group)
        except Exception as e:
            self.logger.debug(f'读取上传组 {upload_group} 失败: {e}')
            return None
        return getattr(group, 'remote_id', None) if group else None

    def _persist_upload_group(self, task: dict, target_uploader) -> None:
        """把上传结果中的稿件归属写回状态库。

        仅当引擎自报的 bvid 与库中记录不一致时才写，避免每个分段都产生一次写操作。
        """
        if self.state_repo is None:
            return
        getter = getattr(target_uploader, 'get_remote_bvid', None)
        if not callable(getter):
            return
        try:
            remote_id = getter()
        except Exception as e:
            self.logger.debug(f'获取上传器稿件标识失败: {e}')
            return
        if not remote_id:
            return

        upload_group = task['upload_group']
        if self._lookup_group_remote_id(upload_group) == remote_id:
            return
        try:
            self.state_repo.get_or_create_upload_group(
                upload_group,
                taskname=task.get('taskname') or '',
                target=task.get('engine') or '',
                account=task.get('args', {}).get('account'),
                engine=task.get('engine'),
            )
            self.state_repo.set_upload_group_remote(upload_group, remote_id)
            self.logger.info(f'已记录上传组 {upload_group} 的稿件：{remote_id}。')
        except Exception as e:
            # 记录失败不应影响上传结果本身
            self.logger.warning(f'记录上传组 {upload_group} 的稿件标识失败: {e}')

    def _gather(self, task, status, desc=''):
        with self._lock:
            self.upload_tasks.pop(task['uuid'], None)
            if status == 'error':
                # Save to failed tasks
                # ignore stream uploads
                if task.get('stream_queue'):
                    task['stream_queue'] = None
                    # task['config']['stream_queue'] = None
                else:
                    self.failed_tasks[task['uuid']] = task
                    self.save_failed_tasks()

                self._pipeSend(
                    event='error',
                    msg=f"上传视频 {[f.path for f in task['files']]} 时出现错误:{desc}",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype=str(type(desc)),
                    data=desc,
                )
            else:
                self._pipeSend(
                    event='end',
                    msg=f"视频 {[f.path for f in task['files']]} 上传完成: {desc}",
                    target=task['source'],
                    request_id=task['request_id'],
                    dtype='dict',
                    data={
                        # 'config': task['config'],
                    },
                )

    def _upload_subprocess(self, task):
        task['status'] = 'uploading'
        try:
            upload_args = task['args']
            upload_group:str = task['upload_group']

            target_uploader = self._get_or_create_uploader(task)

            files = task['files']
            stream_queue = task.get('stream_queue', None)
            retry = upload_args.get('retry', 0)
            if stream_queue:
                retry = 0       # 流式上传无法重试
            status = info = None
            
            while retry >= 0:
                try:
                    if stream_queue:
                        self.logger.info(f"正在同步上传 {files[0].title} 至 {upload_args.get('account')}")
                    else:
                        self.logger.info(f"正在上传 {[f.path for f in files]} 至 {upload_args.get('account')}")
                    # logging.debug(task)
                    res = target_uploader.upload(files=files, stream_queue=stream_queue, **upload_args)
                    
                    if len(res) == 3:
                        status, info, _ = res
                    else:
                        status, info = res

                except KeyboardInterrupt:
                    target_uploader.stop()
                    self.stop()
                    return
                except Exception as e:
                    status, info = False, e
                    self.logger.exception(e)
                
                retry -= 1
                if status or self.stoped:
                    break
                elif retry < 0:
                    self.logger.warning(f'上传 {[f.path for f in files]} 时出现错误，跳过上传.')
                    break
                else:
                    self.logger.warning(f'上传 {[f.path for f in files]} 时出现错误，即将重传.')
                    self.logger.debug(info)
                    time.sleep(60)
            
            if status:
                # 上传成功后才回写稿件归属：此时 bvid 已确定，供重启后复用
                self._persist_upload_group(task, target_uploader)
                self._gather(task, 'info', desc=info)
            else:
                self._gather(task, 'error', desc=info)

            self._free_uploader_pool()
        
        except Exception as e:
            self.logger.exception(e)
            self._gather(task, 'error', desc=e)

    def stop(self):
        self.stoped = True
        self.upload_executors.shutdown(wait=False)
        for upload_group in self._uploader_pool:
            self._uploader_pool[upload_group]['class'].stop()
        
        with self._lock:
            for uuid, task in self.upload_tasks.items():
                if uuid not in self.failed_tasks:
                    self.failed_tasks[uuid] = task
            self.save_failed_tasks()

        self.logger.info('Uploader stopped.')
