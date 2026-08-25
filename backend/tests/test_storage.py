"""Task 4：MinIO 存储客户端（backend/app/storage/client.py）。

纯单元测试：`normalize_filename`/`normalize_key` 为纯函数直接断言；
`presign_put`/`upload_stream`/`presign_get` 用**假 Minio 客户端**注入
`StorageClient(client=FakeMinio())`，只断言参数透传与返回值，**不连真实 MinIO**。
"""

import io
from datetime import timedelta

import pytest

from app.storage import StorageClient, get_storage
from app.storage import client as client_mod
from app.storage.client import normalize_filename, normalize_key


# ---------------------------------------------------------------------------
# normalize_filename / normalize_key（纯函数）
# ---------------------------------------------------------------------------


def test_normalize_filename_lowercase() -> None:
    assert normalize_filename("ABC.MP4") == "abc.mp4"
    assert normalize_filename("My File.TXT") == "my_file.txt"


def test_normalize_filename_spaces_to_underscore() -> None:
    assert normalize_filename("my video.mp4") == "my_video.mp4"
    assert normalize_filename("a  b\tc.mp4") == "a_b_c.mp4"


def test_normalize_filename_strips_special_chars() -> None:
    assert normalize_filename("a!b@c#d.mp4") == "abcd.mp4"
    assert normalize_filename("no_spec!ials.mp4") == "no_specials.mp4"


def test_normalize_filename_chinese_stem_fallback() -> None:
    # 纯中文主干被清洗空 → 回退 file 并保留扩展名
    assert normalize_filename("焊接视频.mp4") == "file.mp4"
    assert normalize_filename("焊缝图像.jpg") == "file.jpg"


def test_normalize_filename_chinese_mixed() -> None:
    # 中英文混合：中文剔除，保留数字与扩展名
    assert normalize_filename("焊接 视频_001.MP4") == "001.mp4"
    assert normalize_filename("信号 数据-02.csv") == "02.csv"


def test_normalize_filename_truncates_overlong_preserving_ext() -> None:
    long = "a" * 300 + ".mp4"
    out = normalize_filename(long)
    assert len(out) <= 255
    assert out.endswith(".mp4")


def test_normalize_filename_truncates_overlong_no_ext() -> None:
    out = normalize_filename("b" * 300)
    assert len(out) == 255
    assert out == "b" * 255


def test_normalize_filename_strips_path_traversal() -> None:
    out = normalize_filename("../evil.mp4")
    assert out == "evil.mp4"
    assert "/" not in out and "\\" not in out
    # 前导点（隐藏文件/父目录）被去除
    assert not out.startswith(".")
    win = normalize_filename(r"..\..\passwd")
    assert "\\" not in win and not win.startswith(".")


def test_normalize_filename_empty_fallback() -> None:
    assert normalize_filename("") == "file"
    assert normalize_filename("!!!") == "file"
    assert normalize_filename("---") == "file"


def test_normalize_key_basic() -> None:
    assert normalize_key("raw/REG-20260815-00248", "Original Video.MP4") == (
        "raw/REG-20260815-00248/original_video.mp4"
    )


def test_normalize_key_prefix_slash_handling() -> None:
    assert normalize_key("processed/WLD-001/align/", "a.MP4") == (
        "processed/WLD-001/align/a.mp4"
    )
    assert normalize_key("/uploads/uuid-123", "b.MP4") == "uploads/uuid-123/b.mp4"


def test_normalize_key_empty_prefix_raises() -> None:
    with pytest.raises(ValueError):
        normalize_key("", "a.mp4")


def test_normalize_key_via_class_staticmethod() -> None:
    # 类上的 staticmethod 与模块级函数同源
    assert StorageClient.normalize_key("raw/R1", "焊接.mp4") == "raw/R1/file.mp4"
    assert StorageClient.normalize_filename("ABC.mp4") == "abc.mp4"


# ---------------------------------------------------------------------------
# presign / upload（假 Minio 客户端，不连真实 MinIO）
# ---------------------------------------------------------------------------


class FakeMinio:
    """记录调用的假 Minio：断言参数透传并返回固定的预签名 URL。"""

    def __init__(self, bucket_exists: bool = True) -> None:
        self.exists = bucket_exists
        self.made_bucket: list[str] = []
        self.bucket_exists_calls = 0
        self.calls: list[tuple] = []

    def bucket_exists(self, bucket: str) -> bool:
        self.bucket_exists_calls += 1
        return self.exists

    def make_bucket(self, bucket: str) -> None:
        self.made_bucket.append(bucket)

    def presigned_get_object(self, bucket, object_name, expires=None, **kw):
        self.calls.append(("get", bucket, object_name, expires))
        secs = int(expires.total_seconds()) if expires else 0
        return f"https://minio.local/{bucket}/{object_name}?expires={secs}"

    def presigned_put_object(self, bucket, object_name, expires=None, **kw):
        self.calls.append(("put", bucket, object_name, expires))
        return f"https://minio.local/{bucket}/{object_name}?signature=put"

    def put_object(self, bucket, object_name, data, length, content_type=None, **kw):
        self.calls.append(("upload", bucket, object_name, length, content_type))
        return object_name

    def remove_object(self, bucket, object_name, **kw):
        self.calls.append(("delete", bucket, object_name))
        return object_name


def _make(fake: FakeMinio) -> StorageClient:
    return StorageClient(client=fake, bucket="aiwelding")


def test_presign_put_returns_key_and_url() -> None:
    fake = FakeMinio()
    storage = _make(fake)
    key, url = storage.presign_put("raw/REG-001", "Original.MP4", 2048, "video/mp4")
    assert key == "raw/REG-001/original.mp4"
    assert url == "https://minio.local/aiwelding/raw/REG-001/original.mp4?signature=put"
    # presigned_put_object(bucket, object_key, expires=30min)
    assert fake.calls[0] == ("put", "aiwelding", key, timedelta(minutes=30))


def test_presign_get_default_expires() -> None:
    fake = FakeMinio()
    storage = _make(fake)
    url = storage.presign_get("raw/REG-001/a.mp4")
    assert url == "https://minio.local/aiwelding/raw/REG-001/a.mp4?expires=3600"
    assert fake.calls[0] == ("get", "aiwelding", "raw/REG-001/a.mp4", timedelta(seconds=3600))


def test_presign_get_custom_expires() -> None:
    fake = FakeMinio()
    storage = _make(fake)
    url = storage.presign_get("videos/long.mp4", expires=86400)
    assert url.endswith("?expires=86400")
    assert fake.calls[0][3] == timedelta(seconds=86400)


def test_upload_stream_passes_through() -> None:
    fake = FakeMinio()
    storage = _make(fake)
    fileobj = io.BytesIO(b"payload")
    storage.upload_stream("raw/REG-001/a.mp4", fileobj, 7, "video/mp4")
    # put_object(bucket, object_key, data, length, content_type=...)
    assert fake.calls[0] == ("upload", "aiwelding", "raw/REG-001/a.mp4", 7, "video/mp4")


def test_delete_object_passes_through() -> None:
    fake = FakeMinio()
    storage = _make(fake)
    storage.delete_object("processed/WLD-001/split/1.jpg")
    assert fake.calls[0] == ("delete", "aiwelding", "processed/WLD-001/split/1.jpg")


def test_bucket_ensure_makes_bucket_when_missing() -> None:
    fake = FakeMinio(bucket_exists=False)
    storage = _make(fake)
    assert fake.made_bucket == []
    storage.presign_get("a/b.mp4")
    assert fake.made_bucket == ["aiwelding"]


def test_bucket_ensure_checked_once() -> None:
    fake = FakeMinio(bucket_exists=True)
    storage = _make(fake)
    storage.presign_get("a/1.mp4")
    storage.presign_put("a", "2.mp4", 10, "video/mp4")
    storage.upload_stream("a/3.mp4", io.BytesIO(b"x"), 1, "text/plain")
    # 首次使用检查一次桶，之后记忆不再重复检查
    assert fake.bucket_exists_calls == 1
    assert fake.made_bucket == []


# ---------------------------------------------------------------------------
# get_storage 懒加载单例
# ---------------------------------------------------------------------------


def test_get_storage_returns_existing_singleton(monkeypatch) -> None:
    fake_obj = StorageClient(client=FakeMinio())
    monkeypatch.setattr(client_mod, "_storage", fake_obj)
    assert get_storage() is fake_obj


def test_get_storage_builds_once(monkeypatch) -> None:
    class FakeMinioCtor:
        def __init__(self, *args, **kwargs) -> None:
            self.made = True

    monkeypatch.setattr(client_mod, "_storage", None)
    monkeypatch.setattr(client_mod, "Minio", FakeMinioCtor)
    s1 = get_storage()
    s2 = get_storage()
    assert isinstance(s1, StorageClient)
    assert s1 is s2


def test_storage_works_through_singleton(monkeypatch) -> None:
    fake = FakeMinio()
    storage = StorageClient(client=fake)
    monkeypatch.setattr(client_mod, "_storage", storage)
    key, url = get_storage().presign_put("uploads/uuid-1", "in.bin", 100, "application/octet-stream")
    assert key == "uploads/uuid-1/in.bin"
    assert url.startswith("https://minio.local/aiwelding/uploads/uuid-1/in.bin")
