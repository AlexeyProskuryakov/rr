def get_interested_fields(source, fields):
    result = {}
    for field in fields:
        result[field] = source.get(field)
    return result
