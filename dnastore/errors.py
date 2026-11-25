"""Ngoại lệ dùng chung của hệ thống dnastore.
Mỗi ngoại lệ mang mã `code` tương ứng trường `reason` trong kết quả chuẩn hóa của orchestrator.
Tác giả kiến trúc: Thái.
"""


class DNAStoreError(Exception):
    code = "FAIL_INTERNAL_ERROR"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code


class ValidationError(DNAStoreError):
    """Dữ liệu đầu vào sai định dạng (packet, metadata, config)."""
    code = "FAIL_INVALID_INPUT"


class FileNotInStore(DNAStoreError):
    """Không tìm thấy file_id trong StorageController."""
    code = "FAIL_STORAGE_ERROR"


class FileAlreadyInStore(DNAStoreError):
    """file_id đã tồn tại trong StorageController khi overwrite=False."""
    code = "FAIL_STORAGE_ERROR"


class RecoveryFailure(DNAStoreError):
    """Bộ phục hồi (Trung/Linh) báo vượt quá khả năng sửa lỗi."""
    code = "FAIL_UNRECOVERABLE"
