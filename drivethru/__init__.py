import sys

# Windows: khi đầu ra bị chuyển hướng (pipe, file, IDE), stdout dùng mã trang ANSI (cp1252) nên print() tiếng Việt báo UnicodeEncodeError.
# Ép stdout và stderr sang UTF-8 để chạy đúng mà không cần đặt biến môi trường PYTHONUTF8.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
