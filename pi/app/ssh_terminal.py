"""Authenticated serial maintenance sessions; SSH destination is always this Pi."""
import atexit
import base64
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import pty
import pwd
import re
import secrets
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

BUFFER = 512 * 1024
IDLE = 15 * 60
LEASE = 90
LIFETIME = 2 * 60 * 60


def dimensions(data):
    cols, rows = data.get('cols', 80), data.get('rows', 24)
    if type(cols) is not int or type(rows) is not int or not 20 <= cols <= 240 or not 5 <= rows <= 100:
        raise ValueError('终端尺寸不正确')
    return cols, rows


def ssh_command(user, directory):
    if not isinstance(user, str) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user):
        raise ValueError('请输入 Pi 的普通系统用户名')
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        raise ValueError('Pi 上不存在此用户')
    if not 1000 <= account.pw_uid < 65534 or account.pw_shell.endswith(('nologin', '/false')):
        raise ValueError('请使用普通桌面账号登录，需要管理员权限时使用 sudo')
    keys = []
    for file in Path('/etc/ssh').glob('ssh_host_*_key.pub'):
        parts = file.read_text().split()
        if len(parts) >= 2:
            keys.append('127.0.0.1 ' + ' '.join(parts[:2]))
    if not keys:
        raise ValueError('本机 SSH 主机公钥缺失，请先修复 SSH 服务')
    known = Path(directory) / 'known_hosts'
    known.write_text('\n'.join(keys) + '\n')
    return ['/usr/bin/ssh', '-F', '/dev/null', '-tt', '-e', 'none',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
            '-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no',
            '-o', 'IdentityAgent=none', '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
            '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=2', '-o', 'NumberOfPasswordPrompts=3',
            '-o', 'LogLevel=ERROR', '-p', '22', '-l', user, '127.0.0.1']


class Session:
    def __init__(self, user, cols, rows, factory=ssh_command):
        self.lock = threading.RLock()
        self.buffer = bytearray()
        self.start = self.end = self.seq = 0
        self.digest = None
        self.salt = secrets.token_bytes(32)
        self.born = self.contact = self.input_at = time.monotonic()
        self.reason = ''
        self.temp = tempfile.TemporaryDirectory(prefix='usbai-ssh-')
        self.fd = -1
        self.proc = None
        try:
            command = factory(user, self.temp.name)
            self.fd, slave = pty.openpty()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                # A single-threaded helper acquires the controlling tty; no unsafe preexec_fn.
                self.proc = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name('ssh_pty_runner.py'))] + command,
                    stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                    env={'PATH': '/usr/bin:/bin', 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
                         'HOME': self.temp.name}, close_fds=True)
            finally:
                os.close(slave)
            os.set_blocking(self.fd, False)
            threading.Thread(target=self.read_loop, daemon=True).start()
        except Exception:
            self.close('启动失败')
            raise

    def read_loop(self):
        try:
            while not self.reason:
                if not select.select([self.fd], [], [], .2)[0]:
                    if self.proc.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(self.fd, 16384)
                except BlockingIOError:
                    continue
                if not data:
                    break
                with self.lock:
                    self.buffer.extend(data)
                    self.end += len(data)
                    if len(self.buffer) > BUFFER:
                        del self.buffer[:-BUFFER]
                    self.start = self.end - len(self.buffer)
        except (OSError, ValueError):
            pass
        finally:
            self.close('SSH 会话已结束')

    def close(self, reason='已断开'):
        with self.lock:
            if self.reason:
                return
            self.reason = reason
            if self.proc:
                try:
                    os.killpg(self.proc.pid, signal.SIGHUP)
                except ProcessLookupError:
                    pass
                try:
                    self.proc.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.proc.wait(timeout=1)
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1
            self.temp.cleanup()

    def poll(self, offset):
        if type(offset) is not int or not 0 <= offset <= self.end:
            raise ValueError('终端输出位置不正确')
        with self.lock:
            self.contact = time.monotonic()
            pos = max(offset, self.start)
            data = bytes(self.buffer[pos-self.start:pos-self.start+32768])
            return dict(data=base64.b64encode(data).decode(), offset=pos+len(data),
                        truncated=offset < self.start, closed=bool(self.reason),
                        reason=self.reason, seq=self.seq, more=pos+len(data) < self.end)

    def input(self, seq, encoded):
        if type(seq) is not int or not isinstance(encoded, str):
            raise ValueError('终端输入格式不正确')
        data = base64.b64decode(encoded, validate=True)
        if not 0 < len(data) <= 4096:
            raise ValueError('每次输入须为 1–4096 字节')
        digest = hmac.digest(self.salt, data, 'sha256')
        with self.lock:
            if seq == self.seq and self.digest == digest:
                return {'seq': self.seq}  # Lost reply: acknowledge, never type twice.
            if seq != self.seq + 1:
                raise ValueError('输入序号冲突，请断开并重新登录；未重复输入')
            if self.reason:
                raise ValueError(self.reason)
            # Reserve before writing. Partial I/O failure terminates the session instead of replaying.
            self.seq, self.digest = seq, digest
            self.contact = self.input_at = time.monotonic()
            sent = 0
            deadline = time.monotonic() + 3
            try:
                while sent < len(data):
                    if time.monotonic() > deadline:
                        raise OSError('PTY input timeout')
                    if select.select([], [self.fd], [], .1)[1]:
                        try:
                            sent += os.write(self.fd, data[sent:])
                        except BlockingIOError:
                            pass
            except OSError:
                self.close('输入中断，请重新登录并检查命令执行状态')
                raise ValueError(self.reason)
            return {'seq': self.seq}

    def resize(self, data):
        cols, rows = dimensions(data)
        with self.lock:
            if not self.reason:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        return {'ok': True}


class TerminalManager:
    def __init__(self, factory=ssh_command):
        self.factory = factory
        self.lock = threading.RLock()
        self.sessions = {}
        self.stopped = threading.Event()
        threading.Thread(target=self.reaper, daemon=True).start()
        atexit.register(self.close)

    def reap(self):
        now = time.monotonic()
        with self.lock:
            for sid, (owner, user, session) in list(self.sessions.items()):
                if now-session.born > LIFETIME:
                    session.close('会话已达两小时，请重新登录')
                elif now-session.contact > LEASE:
                    session.close('USB 或页面断开超过 90 秒，维护会话已关闭')
                elif now-session.input_at > IDLE:
                    session.close('15 分钟无输入，维护会话已关闭')
                # Keep tombstones: a delayed open must never start another shell.
                if now-session.born > LIFETIME + 300:
                    del self.sessions[sid]

    def reaper(self):
        while not self.stopped.wait(2):
            self.reap()

    def close(self):
        self.stopped.set()
        with self.lock:
            for _, _, session in self.sessions.values():
                session.close('服务停止')

    def action(self, data, token):
        sid, action = data.get('session'), data.get('action')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{64}', sid):
            raise ValueError('维护会话标识不正确')
        owner = hashlib.sha256(token.encode()).digest()
        with self.lock:
            if action == 'open' and sid not in self.sessions:
                if sum(not s.reason for _, _, s in self.sessions.values()) >= 2 or len(self.sessions) >= 64:
                    raise ValueError('维护会话数量已达上限，请关闭旧会话或稍后重试')
                cols, rows = dimensions(data)
                session = Session(data.get('user'), cols, rows, self.factory)
                self.sessions[sid] = (owner, data.get('user'), session)
            entry = self.sessions.get(sid)
            if not entry or not hmac.compare_digest(entry[0], owner):
                raise ValueError('维护会话已失效，请重新登录')
            session = entry[2]
        if action == 'open':
            if data.get('user') != entry[1]:
                raise ValueError('会话用户不匹配')
            return {'session': sid, 'closed': bool(session.reason), 'reason': session.reason}
        if action == 'poll':
            return session.poll(data.get('offset', 0))
        if action == 'input':
            return session.input(data.get('seq'), data.get('data'))
        if action == 'resize':
            return session.resize(data)
        if action == 'close':
            session.close()
            return {'ok': True}
        raise ValueError('不支持的维护操作')


MANAGER = TerminalManager()
