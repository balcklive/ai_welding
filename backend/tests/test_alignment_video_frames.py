"""胶片条抽帧端点（`GET …/video-frames`，2026-10）。

对齐页把视频画成**统一轴上的一段**（`[offset, offset + duration]`）来拖 offset，
这个端点给它 N 张按固定间隔抽的帧 + 短期预签名 URL。

本文件钉住三条硬约定：

1. **帧与 offset 无关**（`seek_offset` 恒 0）——改标定后同一帧的对象键与 `t_video` 必须一字不变。
   这是"拖动纯前端、零网络"能成立的前提；破了它就等于每改一次标定都要重抽一遍帧。
2. **全命中不下载视频、不跑 ffmpeg**（`stat_object` 探一下即可）——否则对齐页每打开一次
   都要重下视频 + 跑 N 次 ffmpeg。
3. **超 64MB 在下载前就挡掉**（复用 `_load_video` 的预检），失败逐格如实给原因、不伪造。

基础设施同 `test_split_v3_api.py`：内存 SQLite + StaticPool + 真实 TestClient + 内存假存储 +
imageio-ffmpeg 现生成的真视频。
"""

from __future__ import annotations

import io
import json
import subprocess

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.api.deps import get_current_user
from app.core.db import get_session
from app.main import app
from app.models import User
from app.models.data import AuditLog, DataRecord, DataVersion
from app.services import alignment, media_probe
from app.storage.client import StorageClient

client = TestClient(app)

VIDEO_KEY = "raw/REG-FRAMES-0001/weld.mp4"
OTHER_VIDEO_KEY = "raw/REG-FRAMES-0001/other.mp4"
WELD_ID = "WLD-FRAMES-0001"
VIDEO_SECONDS = 8.0


class FakeStorage:
    """内存假存储：只实现本链路走到的接口。"""

    normalize_key = staticmethod(StorageClient.normalize_key)
    normalize_filename = staticmethod(StorageClient.normalize_filename)

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, object_key: str, data: bytes) -> None:
        self.objects[object_key] = data

    def upload_stream(self, object_key, fileobj, size, content_type):  # noqa: ANN001
        self.objects[object_key] = fileobj.read()

    def get_object(self, object_key: str) -> bytes:
        if object_key not in self.objects:
            raise FileNotFoundError(object_key)
        return self.objects[object_key]

    def stat_object(self, object_key: str) -> int:
        return len(self.objects.get(object_key, b""))

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presign_get(self, object_key: str, expires: int = 3600) -> str:
        return f"https://fake-minio.local/{object_key}?expires={expires}"


@pytest.fixture(scope="module")
def mp4_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("frame_video") / "weld.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"testsrc=size=320x240:rate=25:duration={int(VIDEO_SECONDS)}",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
        ],
        check=True, capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def storage(monkeypatch, mp4_bytes):
    fake = FakeStorage()
    fake.put(VIDEO_KEY, mp4_bytes)
    # `_load_video` / 端点都是函数内延迟导入 `app.storage.get_storage`
    monkeypatch.setattr("app.storage.get_storage", lambda: fake)
    return fake


@pytest.fixture()
def user(db_session) -> User:
    u = User(username="framer", password_hash="x", display_name="抽帧员", role="user")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def api(db_session, user):
    def _session():
        yield db_session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def ready(db_session, user, storage, api):
    """一条带视频的 v1.0 焊缝（**不需要信号导入**——胶片条只看视频）。"""
    record = DataRecord(
        weld_id=WELD_ID, registration_no="REG-FRAMES-0001", source="现场采集", quality="待复核",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(
        record_id=record.id, version_no="v1.0", action="原始数据",
        object_keys=[VIDEO_KEY],
    )
    db_session.add(version)
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=record.weld_id,
    ))
    db_session.commit()
    db_session.refresh(version)
    record.latest_version_id = version.id
    db_session.add(record)
    db_session.commit()
    return record, version.id


def _url(version_id: int, suffix: str = "video-frames") -> str:
    return f"/api/v1/welds/{WELD_ID}/versions/{version_id}/{suffix}"


def _ok(response):
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


# ── 纯函数 ───────────────────────────────────────────────────────────


def test_video_frame_times_are_midpoints_and_clamped():
    times, clamped = alignment.video_frame_times(8.0)
    # 8s / 2s = 4 格，但下限 8 格 —— 格中点即 0.5, 1.5, …, 7.5（不取端点 `duration`）
    assert len(times) == alignment.VIDEO_FRAME_MIN_COUNT == 8
    assert times[0] == 0.5
    assert times[-1] == 7.5
    assert clamped is False

    long_times, clamped_long = alignment.video_frame_times(30 * 60.0)
    assert len(long_times) == alignment.VIDEO_FRAME_MAX_COUNT
    # 截断必须**如实上报**（调用方要靠它记日志，静默截断表现为"长视频后半段没有帧"）
    assert clamped_long is True

    assert alignment.video_frame_times(0) == ([], False)
    assert alignment.video_frame_times(None) == ([], False)


def test_video_frame_key_is_video_scoped_and_stable():
    a = alignment.video_frame_key(WELD_ID, VIDEO_KEY, 3)
    assert a == alignment.video_frame_key(WELD_ID, VIDEO_KEY, 3)
    assert a.startswith(f"processed/{WELD_ID}/video-frames/")
    assert a.endswith("/000003.jpg")
    # **换了视频对象必须换键**：没有这个鉴别位，`_object_exists` 会把上一个视频的帧判成命中复用
    assert a != alignment.video_frame_key(WELD_ID, OTHER_VIDEO_KEY, 3)
    assert alignment.video_frames_manifest_key(WELD_ID, VIDEO_KEY).endswith("/manifest.json")


# ── 端点 ─────────────────────────────────────────────────────────────


def test_video_frames_endpoint_shape_and_jpeg(ready, storage):
    _, version_id = ready
    data = _ok(client.get(_url(version_id)))

    assert data["available"] is True
    assert data["reason"] is None
    assert data["duration"] == pytest.approx(VIDEO_SECONDS, abs=0.5)
    assert data["fps"] == pytest.approx(25.0, abs=1.0)
    assert data["count"] == len(data["frames"]) == 8
    assert data["clamped"] is False

    for index, frame in enumerate(data["frames"]):
        assert frame["index"] == index
        # `t_video` 是**视频轴**时刻（seek_offset=0），格中点
        assert frame["t_video"] == pytest.approx((index + 0.5) * VIDEO_SECONDS / 8, abs=0.02)
        assert frame["object_key"] == alignment.video_frame_key(WELD_ID, VIDEO_KEY, index)
        assert f"expires={alignment.VIDEO_FRAME_EXPIRES_SECONDS}" in frame["url"]
        assert storage.objects[frame["object_key"]].startswith(b"\xff\xd8")  # 真 JPEG
    # JSON 里只有短期 URL，没有二进制
    assert len(json.dumps(data)) < 40_000


def test_video_frames_do_not_move_with_offset(ready):
    """**核心不变量**：帧内容与 offset 无关，改标定不该重抽帧、键与 `t_video` 一字不变。"""
    _, version_id = ready
    before = _ok(client.get(_url(version_id)))

    assert _ok(client.put(_url(version_id, "calibration"), json={"video": {"offset_seconds": 1.0}}))
    after_positive = _ok(client.get(_url(version_id)))
    assert _ok(client.put(_url(version_id, "calibration"), json={"video": {"offset_seconds": -2.5}}))
    after_negative = _ok(client.get(_url(version_id)))

    for other in (after_positive, after_negative):
        assert [f["object_key"] for f in other["frames"]] == [f["object_key"] for f in before["frames"]]
        assert [f["t_video"] for f in other["frames"]] == [f["t_video"] for f in before["frames"]]


def test_video_frames_reuse_without_download_or_ffmpeg(ready, storage, monkeypatch):
    """第二次进页面**不重抽帧、不重下视频**——只有 `stat_object` 探一下 + 读一次小 manifest。

    关掉 `_object_exists` 那条复用判定，本用例必红（第二次会多出一次抽帧与一次下载）。
    """
    _, version_id = ready
    extracted: list[int] = []
    real_analyze = media_probe.analyze_video

    def counting_analyze(data, event_points, seek_offset=0.0):  # noqa: ANN001
        extracted.append(len(event_points))
        return real_analyze(data, event_points, seek_offset=seek_offset)

    reads: list[str] = []
    real_get = storage.get_object

    def counting_get(object_key):
        reads.append(object_key)
        return real_get(object_key)

    monkeypatch.setattr(media_probe, "analyze_video", counting_analyze)
    storage.get_object = counting_get

    first = _ok(client.get(_url(version_id)))
    # 探测一次（0 个点）+ 抽帧一次（8 个点）
    assert extracted == [0, 8], "第一次要探时长并抽满 8 帧"
    assert VIDEO_KEY in reads, "第一次要下载一次视频"
    keys = [f["object_key"] for f in first["frames"]]

    extracted.clear()
    reads.clear()
    again = _ok(client.get(_url(version_id)))

    assert extracted == [], "第二次不该再跑 ffmpeg"
    # 只读那个小 manifest（判命中要靠它），**视频一个字节都不下载**
    assert reads == [alignment.video_frames_manifest_key(WELD_ID, VIDEO_KEY)]
    assert VIDEO_KEY not in reads
    assert [f["object_key"] for f in again["frames"]] == keys
    assert all(f["url"] for f in again["frames"]), "复用也要给新的短期 URL"


def test_video_frames_reason_when_video_missing(ready, db_session, storage, user):
    _, version_id = ready
    storage.objects.pop(VIDEO_KEY)  # 对象键还在版本里，但对象不可读
    data = _ok(client.get(_url(version_id)))
    assert data["available"] is False
    assert data["frames"] == []
    assert data["reason"] and "不可读" in data["reason"]
    assert data["duration"] is None

    # 加工版自身没有视频键时**回退到 v1.0**（原始文件锚在 v1.0）——这是有意的，不是"没有视频"
    empty = DataVersion(record_id=ready[0].id, version_no="v1.1", action="去噪处理", object_keys=[])
    db_session.add(empty)
    db_session.commit()
    db_session.refresh(empty)
    assert _ok(client.get(_url(empty.id)))["reason"] and "不可读" in _ok(client.get(_url(empty.id)))["reason"]

    # 真的没有视频（v1.0 只有图片）→ 另一条原因
    bare_record = DataRecord(
        weld_id="WLD-FRAMES-NOVIDEO", registration_no="REG-FRAMES-0002",
        source="现场采集", quality="待复核",
    )
    db_session.add(bare_record)
    db_session.commit()
    db_session.refresh(bare_record)
    bare_version = DataVersion(
        record_id=bare_record.id, version_no="v1.0", action="原始数据",
        object_keys=["raw/REG-FRAMES-0002/seam.jpg"],
    )
    db_session.add(bare_version)
    db_session.add(AuditLog(
        user_id=user.id, action="create", resource_type="weld", resource_id=bare_record.weld_id,
    ))
    db_session.commit()
    db_session.refresh(bare_version)
    bare = _ok(client.get(
        f"/api/v1/welds/{bare_record.weld_id}/versions/{bare_version.id}/video-frames"
    ))
    assert bare["available"] is False
    assert bare["reason"] == "未上传视频文件"


def test_video_frames_oversize_does_not_download(ready, storage, monkeypatch):
    """超限必须在**下载之前**挡掉（`_load_video` 用 stat_object 预检）——所以 get_object 计数为 0。"""
    _, version_id = ready
    reads: list[str] = []
    real_get = storage.get_object

    def counting_get(object_key):
        reads.append(object_key)
        return real_get(object_key)

    storage.get_object = counting_get
    monkeypatch.setattr(media_probe, "MAX_VIDEO_PROBE_BYTES", 1024)

    data = _ok(client.get(_url(version_id)))
    assert data["available"] is False
    assert data["reason"] and "跳过视频探测" in data["reason"]
    # manifest 的探测读不算数——关键是**视频对象一个字节都没下载**
    assert VIDEO_KEY not in reads


def test_video_frames_partial_and_ffmpeg_failure(ready, monkeypatch):
    """抽帧部分失败 → 只让缺的那格没有帧；整段失败 → 如实给原因但**仍给时长**（条还能画、还能拖）。"""
    _, version_id = ready
    real_analyze = media_probe.analyze_video

    def partial(data, event_points, seek_offset=0.0):  # noqa: ANN001
        meta, frames = real_analyze(data, event_points, seek_offset=seek_offset)
        return meta, frames[:-1]  # 少一格

    monkeypatch.setattr(media_probe, "analyze_video", partial)
    data = _ok(client.get(_url(version_id)))
    assert data["count"] == 8
    assert len(data["frames"]) == 8, "格数不变，缺帧只是该格没有 url"
    assert sum(1 for f in data["frames"] if f["url"]) == 7
    missing = [f for f in data["frames"] if f["url"] is None]
    assert len(missing) == 1 and missing[0]["object_key"] is None, "缺帧不拿别的格顶替"

    def boom(data, event_points, seek_offset=0.0):  # noqa: ANN001
        raise RuntimeError("ffmpeg 不可用")

    monkeypatch.setattr(media_probe, "analyze_video", boom)
    failed = _ok(client.get(_url(version_id)))
    assert failed["available"] is False
    assert failed["frames"] == []
    # 探测就炸了 → 连时长都给不了，前端只能走空态（不编造条宽）
    assert failed["duration"] is None
    assert failed["reason"] and "抽帧失败" in failed["reason"]


def test_video_frames_auth_and_resolution(db_session, user, storage):
    """未登录 401；别人的焊缝 403；未知焊缝 40401；跨焊缝版本 40402。

    刻意**不用 `api` fixture**——它会把 `get_current_user` 覆盖成固定用户，就测不到 401 了。
    """
    other = User(username="other", password_hash="x", display_name="他人", role="user")
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    record = DataRecord(
        weld_id=WELD_ID, registration_no="REG-FRAMES-0009", source="现场采集", quality="待复核",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    version = DataVersion(record_id=record.id, version_no="v1.0", action="原始数据",
                          object_keys=[VIDEO_KEY])
    db_session.add(version)
    db_session.add(AuditLog(
        user_id=other.id, action="create", resource_type="weld", resource_id=record.weld_id,
    ))
    db_session.commit()
    db_session.refresh(version)

    def _session():
        yield db_session

    app.dependency_overrides[get_session] = _session
    try:
        # 不带 Authorization 头 → 401
        assert client.get(_url(version.id)).status_code == 401

        # 已登录但不是 owner → 403
        app.dependency_overrides[get_current_user] = lambda: user
        forbidden = client.get(_url(version.id))
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == 40300

        # owner 本人：焊缝不存在 40401 / 版本不属于该焊缝 40402
        app.dependency_overrides[get_current_user] = lambda: other
        assert client.get("/api/v1/welds/WLD-NOPE/versions/1/video-frames").json()["code"] == 40401
        assert client.get(
            f"/api/v1/welds/{WELD_ID}/versions/999999/video-frames"
        ).json()["code"] == 40402
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
