"""One persistent STA connection for borrowed user windows."""
import concurrent.futures
import queue
import threading
from .errors import WriterError

class LiveWorker:
    def __init__(self):
        self.jobs = queue.Queue()
        self.busy = False
        self.thread = threading.Thread(target=self.run, daemon=True, name='hangul-live-sta')
        self.thread.start()

    def run(self):
        from .backend import initialize_sta, finalize_sta
        from . import live
        initialize_sta()
        try:
            while True:
                item = self.jobs.get()
                if item is None: break
                job, future = item
                try: future.set_result(live.handle(job))
                except WriterError as e: future.set_exception(e)
                except Exception as e: future.set_exception(WriterError('BACKEND_FAILED', '열린 문서 연결 실패: ' + str(e)))
        finally:
            live.disconnect_all()
            finalize_sta()

    def __call__(self, job):
        if self.busy: raise WriterError('LIVE_RECOVERY_REQUIRED', '열린 문서 연결이 시간 초과 후 아직 종료되지 않았습니다. 창을 확인한 뒤 플러그인을 다시 연결하세요.')
        future = concurrent.futures.Future()
        cancelled = threading.Event()
        self.jobs.put((dict(job, _cancelled=cancelled), future))
        try: return future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            cancelled.set()
            self.busy = True
            raise WriterError('HANCOM_TIMEOUT', '열린 문서 작업이 시간 초과됐습니다. 사용자 창은 닫지 않았습니다. 반복하지 말고 창과 복원용 사본을 확인하세요.') from None

    def close(self):
        self.jobs.put(None)
        self.thread.join(timeout=1)
