"""Dependency-free enforcement of every keyword in the supplied JSON schema."""


def schema_errors(value, schema, path="$", errors=None):
    if errors is None:
        errors = []
    kinds = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
             "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
    kind = schema.get("type")
    if kind:
        allowed = [kind] if isinstance(kind, str) else kind
        if not any(kinds[k](value) for k in allowed):
            errors.append(path + ": invalid type")
            return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": invalid enum")
    if "oneOf" in schema and sum(not schema_errors(value, sub, path) for sub in schema["oneOf"]) != 1:
        errors.append(path + ": expected exactly one alternative")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(path + ": missing " + key)
        if schema.get("additionalProperties") is False:
            for key in value.keys() - properties.keys():
                errors.append(path + ": unknown " + key)
        for key, child in properties.items():
            if key in value:
                schema_errors(value[key], child, path + "." + key, errors)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            errors.append(path + ": invalid array length")
        for i, item in enumerate(value):
            if "items" in schema:
                schema_errors(item, schema["items"], path + "[%d]" % i, errors)
    return errors
