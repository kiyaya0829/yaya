"""Store a personal API key separately from journal backups, protected by Windows DPAPI."""
import ctypes
from ctypes import wintypes
import os


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise OSError('密钥保存仅支持 Windows；其他系统请使用 ALPHAVANTAGE_API_KEY 环境变量。')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'Yaya API key', None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise OSError(f'无法读取或保存本机密钥（Windows 错误 {ctypes.get_last_error()}），请重新填写。')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def load_key(directory):
    override = os.environ.get('ALPHAVANTAGE_API_KEY', '').strip()
    if override:
        return override
    path = directory / 'api-key.dpapi'
    return protect(path.read_bytes(), decrypt=True).decode('utf-8') if path.exists() else ''


def save_key(directory, key):
    path = directory / 'api-key.dpapi'
    if not key.strip():
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(protect(key.strip().encode('utf-8')))
    temporary.replace(path)
