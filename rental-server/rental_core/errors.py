class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details

    def to_dict(self):
        payload = {"error": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload
