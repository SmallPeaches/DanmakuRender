from functools import wraps
from DMR.LiveAPI.tars import tarscore


STANDARD_CHARSET = 'utf-8'


def auto_decode_fields(cls):
    """自动解码类中的bytes类型数据，包括vector和map中的字符串"""
    original_read_from = cls.readFrom

    def _decode_recursive(obj):
        """递归解码对象中的bytes字段"""
        if isinstance(obj, bytes):
            try:
                return obj.decode(STANDARD_CHARSET)
            except UnicodeDecodeError:
                return obj
        elif isinstance(obj, list):
            for i in range(len(obj)):
                obj[i] = _decode_recursive(obj[i])
        elif isinstance(obj, dict):
            keys_to_update = []
            for key in obj.keys():
                decoded_key = _decode_recursive(key)
                decoded_value = _decode_recursive(obj[key])
                keys_to_update.append((key, decoded_key, decoded_value))
            for old_key, new_key, new_value in keys_to_update:
                if old_key != new_key:
                    del obj[old_key]
                    obj[new_key] = new_value
                else:
                    obj[old_key] = new_value
        elif hasattr(obj, '__dict__'):
            for attr_name, attr_value in vars(obj).items():
                setattr(obj, attr_name, _decode_recursive(attr_value))
        return obj

    @staticmethod
    @wraps(original_read_from)
    def wrapped_read_from(ios: tarscore.TarsInputStream):
        value = original_read_from(ios)
        for attr_name, attr_value in vars(value).items():
            setattr(value, attr_name, _decode_recursive(attr_value))
        return value

    cls.readFrom = wrapped_read_from
    return cls
