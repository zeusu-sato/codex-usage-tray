class QuotaError(Exception):
    """Only stable local error categories; never expose raw server errors."""



    def __init__(self, code, reason=None, detail=None):
        super().__init__(code)
        self.reason = reason
        self.detail = detail
