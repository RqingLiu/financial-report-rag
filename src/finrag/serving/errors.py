"""Safe static domain codes; never wrap provider/DB exception text."""


class ServingError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)
