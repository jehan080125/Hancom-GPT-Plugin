class WriterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def result(self):
        return {"ok": False, "error": self.code, "message": str(self)}
