import os

def get_config(key: str, default=None):
    return os.getenv(key, default)
