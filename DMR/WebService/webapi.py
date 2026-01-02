import logging
import threading
import queue
import secrets
import os
import yaml
import glob
from flask import Flask, request, render_template, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime

from DMR.utils import *

class WebApi:
    def __init__(
            self,
            pipe:Tuple[queue.Queue, queue.Queue],
            engine=None,
            host='0.0.0.0',
            port=5000,
            force_login=True,
            username='admin',
            password='admin',
            **kwargs,
        ) -> None:
        self.send_queue, self.recv_queue = pipe
        self.engine = engine
        self.kwargs = kwargs
        
        # WebAPI Config
        self.host = host
        self.port = port
        self.force_login = force_login
        self.username = username
        self.password = password
        
        # 强制使用高强度随机密钥，每次启动自动生成，极大提高安全性
        # 注意：这意味着每次重启程序后，所有已登录用户都需要重新登录
        self.secret_key = secrets.token_hex(32)
        self.logger = logging.getLogger(__name__)
        self.stoped = True

        self.webapp = None
        self.webapp_thread = None

    def login_required(self, f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if self.force_login and 'logged_in' not in session:
                return redirect(url_for('login', next=request.url))
            return f(*args, **kwargs)
        return decorated_function

    def create_app(self):
        # Silence Flask/Werkzeug non-error logs
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        app = Flask(__name__, template_folder='templates')
        app.secret_key = self.secret_key
        app.logger = self.logger

        @app.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                username = request.form['username']
                password = request.form['password']
                if username == self.username and password == self.password:
                    session['logged_in'] = True
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', error='Invalid credentials')
            return render_template('login.html')

        @app.route('/logout')
        def logout():
            session.pop('logged_in', None)
            return redirect(url_for('login'))

        @app.route('/')
        @self.login_required
        def index():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return self.get_tasks_data()
            return render_template('index.html', **self.get_tasks_data())

        # 保留之前的兼容性
        @app.route('/api/put_message', methods=['POST'])
        @self.login_required
        def api_v1_func():
            req_data = request.get_json()
            message = PipeMessage(**req_data['data'])
            self.send_queue.put(message)
            return 'success', 200

        @app.route('/tasks')
        @self.login_required
        def tasks_page():
            return render_template('tasks.html', **self.get_tasks_data())

        @app.route('/api/tasks')
        @self.login_required
        def tasks_api():
            return self.get_tasks_data()

        @app.route('/api/check_config', methods=['POST'])
        @self.login_required
        def check_config_api():
            try:
                content = request.json.get('content')
                yaml.safe_load(content)
                return {'valid': True, 'message': '配置文件格式正确 (Valid YAML)'}
            except Exception as e:
                return {'valid': False, 'message': f'配置文件格式错误: {e}'}

        @app.route('/config')
        @self.login_required
        def config_list():
            configs = []
            # List all configs in configs/ folder (except global.yml maybe, or include it)
            # User said "Edit existing config files (excluding Global.yml)"
            config_dir = 'configs'
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            
            files = glob.glob(os.path.join(config_dir, '*.yml'))
            for f in files:
                filename = os.path.basename(f)
                if filename.lower() == 'global.yml':
                    continue
                
                # Extract taskname if possible (DMR-taskname.yml)
                taskname = filename
                if filename.startswith('DMR-'):
                    taskname = filename[4:-4]
                elif filename.endswith('.yml'):
                    taskname = filename[:-4]
                
                configs.append({
                    'filename': filename,
                    'taskname': taskname
                })
            
            return render_template('config_list.html', configs=configs)

        @app.route('/config/create', methods=['GET', 'POST'])
        @self.login_required
        def config_create():
            return config_edit(filename=None)

        @app.route('/config/edit/<filename>', methods=['GET', 'POST'])
        @self.login_required
        def config_edit(filename):
            config_dir = 'configs'
            content = ""
            check_result = None
            
            if filename:
                filepath = os.path.join(config_dir, filename)
                if not os.path.exists(filepath):
                    flash(f'File {filename} not found.', 'error')
                    return redirect(url_for('config_list'))
                
                if request.method == 'GET':
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

            if request.method == 'POST':
                content = request.form['content']
                # Normalize line endings to avoid triple spacing (CRLF -> LF)
                content = content.replace('\r\n', '\n')
                action = request.form['action']
                new_filename = request.form.get('new_filename', filename)
                
                # Validation
                try:
                    yaml.safe_load(content)
                    valid = True
                    check_result = "YAML Format OK"
                except Exception as e:
                    valid = False
                    check_result = f"YAML Error: {e}"
                
                if action == 'save':
                    if filename and filename.startswith('example-'):
                        flash('示例文件不支持修改。', 'error')
                        return redirect(url_for('config_list'))
                    
                    if valid:
                        if not new_filename.endswith('.yml'):
                             new_filename += '.yml'
                        
                        save_path = os.path.join(config_dir, new_filename)
                        try:
                            with open(save_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            flash(f'Config {new_filename} saved successfully.', 'success')
                            return redirect(url_for('config_list'))
                        except Exception as e:
                            flash(f'Error saving file: {e}', 'error')
                    else:
                        flash('Invalid YAML format. Please fix errors before saving.', 'error')

            return render_template('config_edit.html', filename=filename, content=content, check_result=check_result)

        @app.route('/config/delete/<filename>', methods=['POST'])
        @self.login_required
        def config_delete(filename):
            config_dir = 'configs'
            if filename:
                if filename.startswith('example-'):
                    flash('示例文件不支持删除。', 'error')
                    return redirect(url_for('config_list'))
                
                filepath = os.path.join(config_dir, filename)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        flash(f'Config {filename} deleted successfully.', 'success')
                    except Exception as e:
                        flash(f'Error deleting file: {e}', 'error')
                else:
                    flash(f'File {filename} not found.', 'error')
            return redirect(url_for('config_list'))

        @app.route('/api/failed_uploads/retry/<uuid>', methods=['POST'])
        @self.login_required
        def failed_uploads_retry(uuid):
            if self.engine and 'uploader' in self.engine.plugin_dict:
                uploader = self.engine.plugin_dict['uploader']['class']
                if uploader:
                    if uploader.retry_task(uuid):
                        return {'status': 'success', 'message': 'Task retry scheduled.'}
                    else:
                        return {'status': 'error', 'message': 'Task not found or failed to retry.'}
            return {'status': 'error', 'message': 'Uploader not available.'}

        @app.route('/api/failed_uploads/delete/<uuid>', methods=['POST'])
        @self.login_required
        def failed_uploads_delete(uuid):
            if self.engine and 'uploader' in self.engine.plugin_dict:
                uploader = self.engine.plugin_dict['uploader']['class']
                if uploader:
                    if uploader.delete_failed_task(uuid):
                        return {'status': 'success', 'message': 'Task deleted.'}
                    else:
                        return {'status': 'error', 'message': 'Task not found.'}
            return {'status': 'error', 'message': 'Uploader not available.'}

        @app.route('/api/failed_renders/retry/<uuid>', methods=['POST'])
        @self.login_required
        def failed_renders_retry(uuid):
            if self.engine and 'render' in self.engine.plugin_dict:
                render = self.engine.plugin_dict['render']['class']
                if render:
                    if render.retry_task(uuid):
                        return {'status': 'success', 'message': 'Task retry scheduled.'}
                    else:
                        return {'status': 'error', 'message': 'Task not found or failed to retry.'}
            return {'status': 'error', 'message': 'Render not available.'}

        @app.route('/api/failed_renders/delete/<uuid>', methods=['POST'])
        @self.login_required
        def failed_renders_delete(uuid):
            if self.engine and 'render' in self.engine.plugin_dict:
                render = self.engine.plugin_dict['render']['class']
                if render:
                    if render.delete_failed_task(uuid):
                        return {'status': 'success', 'message': 'Task deleted.'}
                    else:
                        return {'status': 'error', 'message': 'Task not found.'}
            return {'status': 'error', 'message': 'Render not available.'}

        return app

    def get_tasks_data(self):
        # Get Recording Tasks
        recording_tasks = []
        if self.engine and 'downloader' in self.engine.plugin_dict:
            downloader = self.engine.plugin_dict['downloader']['class']
            if downloader:
                for taskname, task in downloader.download_tasks.items():
                    # Basic info
                    status = 1 if not getattr(task, 'stoped', True) else 0
                    duration = "未开播"
                    
                    if status == 1:
                        if hasattr(task, 'segment_start_time'):
                             delta = datetime.now() - task.segment_start_time
                             duration = str(delta).split('.')[0]
                    
                    recording_tasks.append({
                        'name': taskname,
                        'platform': task.plat,
                        'url': task.url,
                        'status': status,
                        'duration': duration
                    })

        # Get Upload Tasks
        upload_tasks_list = []
        failed_tasks_list = []
        if self.engine and 'uploader' in self.engine.plugin_dict:
            uploader = self.engine.plugin_dict['uploader']['class']
            if uploader:
                for uuid, task in uploader.upload_tasks.items():
                    upload_tasks_list.append({
                        'files': [{'name': os.path.basename(f.path)} for f in task.get('files', [])],
                        'account': task.get('args', {}).get('account', 'Unknown'),
                        'engine': task.get('engine', 'Unknown'),
                        'is_sync': bool(task.get('stream_queue')),
                        'status': task.get('status', 'waiting')
                    })
                
                for uuid, task in uploader.failed_tasks.items():
                    failed_tasks_list.append({
                        'uuid': uuid,
                        'files': [{'name': os.path.basename(f.path)} for f in task.get('files', [])],
                        'account': task.get('args', {}).get('account', 'Unknown'),
                        'engine': task.get('engine', 'Unknown'),
                        'command': task.get('command'),
                    })

        # Get Render Tasks
        render_tasks_list = []
        failed_renders_list = []
        if self.engine and 'render' in self.engine.plugin_dict:
            render = self.engine.plugin_dict['render']['class']
            if render:
                for uuid, task in render.render_tasks.items():
                    video_path = task.get('video').path if task.get('video') else 'Unknown'
                    render_tasks_list.append({
                        'video': os.path.basename(video_path),
                        'output': os.path.basename(task.get('output', 'Unknown')),
                        'mode': task.get('mode', 'Unknown'),
                        'status': task.get('status', 'waiting')
                    })
                
                for uuid, task in render.failed_tasks.items():
                    video_path = task.get('video').path if task.get('video') else 'Unknown'
                    failed_renders_list.append({
                        'uuid': uuid,
                        'video': os.path.basename(video_path),
                        'output': os.path.basename(task.get('output', 'Unknown')),
                        'mode': task.get('mode', 'Unknown'),
                    })
        
        return {
            'recording_tasks': recording_tasks, 
            'upload_tasks': upload_tasks_list, 
            'failed_tasks': failed_tasks_list,
            'render_tasks': render_tasks_list,
            'failed_renders': failed_renders_list
        }

    def start_helper(self):
        self.webapp = self.create_app()
        self.webapp.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def start(self):
        self.webapp_thread = threading.Thread(target=self.start_helper, daemon=True)
        self.webapp_thread.start()
        self.logger.info(f'DanmakuRender 5 started at http://{self.host}:{self.port}')

    def stop(self):
        self.stoped = True
        # Flask doesn't have a clean stop method when running with .run(), 
        # but since it's a daemon thread, it will die when main process dies.
        # Alternatively, we could use a production server like waitress/gunicorn but that adds dependencies.
