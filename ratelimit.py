"""进程内登录限流与锁定。

滑动窗口计数:同一 key(按 IP、按用户名)在 window 秒内失败达到 max_attempts 次,
锁定 lockout 秒。成功登录清零。线程安全。

局限(生产注意):状态在进程内存,多进程/多实例(gunicorn 多 worker)下各自独立,
且重启即丢失。真正的生产环境应改用 Redis 后端 + Flask-Limiter。此实现足以为单进程
自托管场景挡住暴力破解与脚本爬取。
"""
import threading
import time
from collections import defaultdict, deque


class LoginThrottle:
    def __init__(self, max_attempts=5, window=300, lockout=900):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self._fails = defaultdict(deque)   # key -> 失败时间戳队列
        self._locked = {}                  # key -> 解锁时间戳
        self._lock = threading.Lock()

    def locked_for(self, key):
        """返回该 key 还需锁定的剩余秒数(0 表示未锁定)。"""
        now = time.time()
        with self._lock:
            until = self._locked.get(key)
            if until is None:
                return 0
            remaining = until - now
            if remaining <= 0:
                self._locked.pop(key, None)
                self._fails.pop(key, None)
                return 0
            return int(remaining) + 1

    def record_failure(self, key):
        """记录一次失败;若触发锁定返回锁定秒数,否则返回 0。"""
        now = time.time()
        with self._lock:
            dq = self._fails[key]
            dq.append(now)
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.max_attempts:
                self._locked[key] = now + self.lockout
                dq.clear()
                return self.lockout
            return 0

    def remaining_attempts(self, key):
        now = time.time()
        with self._lock:
            dq = self._fails[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            return max(0, self.max_attempts - len(dq))

    def reset(self, key):
        with self._lock:
            self._fails.pop(key, None)
            self._locked.pop(key, None)
