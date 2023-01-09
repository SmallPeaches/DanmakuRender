import os
import signal
import sys
import subprocess
import logging

class FFmpegRender():
    def __init__(self, output_dir:str, hwaccel_args:list, vencoder:str, vencoder_args:list, aencoder:str, aencoder_args:list, ffmpeg:str, debug=False, **kwargs):
        self.rendering = False
        self.output_dir = output_dir
        self.hwaccel_args = hwaccel_args if hwaccel_args is not None else []
        self.vencoder = vencoder
        self.vencoder_args = vencoder_args
        self.aencoder = aencoder
        self.aencoder_args = aencoder_args
        self.ffmpeg = ffmpeg
        self.debug = debug

    def render_helper(self, video:str, danmaku:str, output:str, to_stdout:bool=False):
        ffmpeg_args = [self.ffmpeg, '-y']
        ffmpeg_args += self.hwaccel_args

        ffmpeg_args +=  [
                        '-fflags','+discardcorrupt',
                        '-i', video,
                        '-vf', 'subtitles=filename=%s'%danmaku.replace('\\','/'),

                        '-c:v',self.vencoder,
                        *self.vencoder_args,
                        '-c:a',self.aencoder,
                        *self.aencoder_args,

                        '-movflags','frag_keyframe',
                        output,
                        ]
        
        logging.debug('Danmaku Render args:')
        logging.debug(ffmpeg_args)

        if to_stdout or self.debug:
            proc = subprocess.Popen(ffmpeg_args, stdin=sys.stdin, stdout=sys.stdout, stderr=subprocess.STDOUT,bufsize=10**8)
        else:
            proc = subprocess.Popen(ffmpeg_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,bufsize=10**8)

        return proc

    def render_one(self, video:str, danmaku:str, output:str, **kwargs):
        if os.path.exists(output):
            raise RuntimeError(f'已经存在文件 {output}，跳过渲染.')
        self.render_proc = self.render_helper(video,danmaku,output,to_stdout=self.debug)
        if self.debug:
            self.render_proc.wait()
            return True
        else:
            log = ''
            info = None
            for line in self.render_proc.stdout.readlines():
                try:
                    line = line.decode('utf-8').strip()
                except UnicodeError as e:
                    logging.error(e)
                    logging.error(line)
                log += line+'\n'
                if line.startswith('video:'):
                    info = line
            logging.debug(f'[Render Process]:{log}')
            if info:
                # logging.info(f'{output} 渲染完成, {info}')
                return info
            else:
                # logging.error(f'{output} 渲染错误:\n{log}')
                raise RuntimeError(f'{output} 渲染错误:\n{log}')

    def stop(self):
        try:
            out, _ = self.render_proc.communicate(b'q',timeout=5)
            logging.debug(out)
        except subprocess.TimeoutExpired:
            try:
                self.render_proc.send_signal(signal.SIGINT)
                out, _ = self.render_proc.communicate()
                logging.debug(out)
            except Exception as e:
                logging.exception(e)
        except Exception as e:
            logging.exception(e)