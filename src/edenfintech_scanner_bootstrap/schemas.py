from __future__ import annotations


class SchemaValidationError(ValueError):
    pass


def _resolve_ref(root_schema: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise SchemaValidationError(f"unsupported schema ref: {ref}")

    node: object = root_schema
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaValidationError(f"unresolvable schema ref: {ref}")
        node = node[part]

    if not isinstance(node, dict):
        raise SchemaValidationError(f"schema ref did not resolve to an object: {ref}")
    return node


def _matches_type(value: object, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    raise SchemaValidationError(f"unsupported schema type: {expected_type}")


def validate_instance(instance: object, schema: dict, *, root_schema: dict | None = None, path: str = "$") -> None:
    root = root_schema or schema
    if "$ref" in schema:
        validate_instance(instance, _resolve_ref(root, schema["$ref"]), root_schema=root, path=path)
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        valid_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(instance, item) for item in valid_types):
            expected = ", ".join(valid_types)
            raise SchemaValidationError(f"{path}: expected type {expected}")

    if "const" in schema and instance != schema["const"]:
        raise SchemaValidationError(f"{path}: expected constant value {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}: value {instance!r} is not in enum {schema['enum']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaValidationError(f"{path}: value {instance} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaValidationError(f"{path}: value {instance} exceeds maximum {schema['maximum']}")

    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        raise SchemaValidationError(f"{path}: string length is below minLength {schema['minLength']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaValidationError(f"{path}: item count is below minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                validate_instance(item, item_schema, root_schema=root, path=f"{path}[{idx}]")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaValidationError(f"{path}: missing required key {key}")

        for key, child_schema in schema.get("properties", {}).items():
            if key in instance:
                validate_instance(instance[key], child_schema, root_schema=root, path=f"{path}.{key}")


def validate_all_errors(instance: object, schema: dict, *, root_schema: dict | None = None, path: str = "$") -> list[str]:
    """Like validate_instance but collects all errors instead of raising on first."""
    root = root_schema or schema
    errors: list[str] = []

    if "$ref" in schema:
        return validate_all_errors(instance, _resolve_ref(root, schema["$ref"]), root_schema=root, path=path)

    expected_type = schema.get("type")
    if expected_type is not None:
        valid_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(instance, item) for item in valid_types):
            expected = ", ".join(valid_types)
            errors.append(f"{path}: expected type {expected}")
            return errors  # wrong type — skip deeper checks

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant value {schema['const']!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} is not in enum {schema['enum']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: value {instance} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: value {instance} exceeds maximum {schema['maximum']}")

    if isinstance(instance, str) and "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(f"{path}: string length is below minLength {schema['minLength']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: item count is below minItems {schema['minItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                errors.extend(validate_all_errors(item, item_schema, root_schema=root, path=f"{path}[{idx}]"))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key}")

        for key, child_schema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate_all_errors(instance[key], child_schema, root_schema=root, path=f"{path}.{key}"))

    return errors
