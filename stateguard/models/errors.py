class ModelError(RuntimeError):
    pass


class ModelConfigError(ModelError):
    pass


class ModelResponseError(ModelError):
    pass
