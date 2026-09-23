"""Validate the published wire contracts before ingestion (including JSON NaN)."""
import json
import math
from pathlib import Path
from functools import lru_cache
from jsonschema import Draft202012Validator


@lru_cache
def validator(kind):
    schema = json.loads((Path(__file__).parent / 'schemas' / f'{kind}.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_artifact(data, kind):
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('nonfinite numeric value')
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        elif isinstance(value, list):
            for v in value:
                finite(v)
    finite(data)
    errors = sorted(validator(kind).iter_errors(data), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError(f'{kind} schema {list(error.path)}: {error.message}')
