class FakeForm:
    def __init__(self, **fields):
        self._fields = {key: value if isinstance(value, list) else [value] for key, value in fields.items()}

    def get(self, key, default=""):
        values = self._fields.get(key)
        return values[0] if values else default

    def getlist(self, key):
        return list(self._fields.get(key, []))


def make_field(**overrides):
    field = {
        "name": "field_a",
        "type": "text",
        "required": True,
        "label": "Label",
        "note": {},
    }
    field.update(overrides)
    return field
