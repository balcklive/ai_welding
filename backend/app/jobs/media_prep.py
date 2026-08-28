"""media_prep handler：登记挂载视频后的浏览器可播性预处理（转码预览版）。

背景：工业相机常输出 MPEG-4 Part 2（`mp4v`）编码，主流浏览器 `<video>` 无法解码
（MediaError code=4），且 moov 索引常在文件尾（无 faststart），即使能解码也要下完
整个文件才能播。job 链路：

```
POST /registrations/{id}/raw-files 挂载含视频扩展名 key
  └ 同事务 create_job("media_prep", result={weld_id, version_id, object_key})
      └ executor → handle → run_media_prep(session, job)
          ├ MinIO 读源视频（≤ MAX_VIDEO_PROBE_BYTES）
          ├ 已是浏览器友好编码（BROWSER_FRIENDLY_CODECS）+ faststart
          │   └ 预览 key = 原始 key（不转码）
          ├ 否则 media_probe.transcode_preview → H.264 + faststart
          │   └ 上传 processed/{weld_id}/video/{stem}.preview.mp4
          └ mark_succeeded(result={object_key, preview_key, transcode, codec})
```

消费方：`POST /annotation-tasks`（source=video）创建视频锚点样本时查最新 succeeded
media_prep job，用 `preview_key` 作为锚点 `video_key`——原始版本 object_keys 不动。

坑：
- 与 signal_ingest 同理，**handler 内自捕获异常写 failed 后正常返回**——executor 的
  failed 兜底会先 rollback 丢弃 handler 写过的状态，不能把业务异常重抛；
- 写 failed 前先 `rollback()` 并**重取** job 行（rollback 会把实例属性过期）；
- 转码在 executor 单线程轮询内执行，长视频转码期间其他 job 排队（可接受）。
"""

from __future__ import annotations

import io
from pathlib import Path

from loguru import logger
from sqlmodel import Session

from app.jobs.executor import register_handler
from app.models.jobs import Job
from app.services import media_probe
from app.services.jobs import mark_failed, mark_succeeded


def run_media_prep(session: Session, job: Job) -> None:
    """media_prep handler 领域逻辑：下载源视频 → 判定/转码 → 上传预览 → 回填 job。

    任何失败 mark_failed（message 进 job.error），**不重抛**（同 signal_ingest 约定）。
    """
    result = job.result or {}
    object_key = result.get("object_key")
    weld_id = result.get("weld_id")
    try:
        from app.storage import get_storage  # 延迟导入，测试 monkeypatch

        storage = get_storage()
        data = storage.get_object(object_key)
        if len(data) > media_probe.MAX_VIDEO_PROBE_BYTES:
            raise ValueError(
                f"Video is too large ({len(data)} B > {media_probe.MAX_VIDEO_PROBE_BYTES} B); preview transcoding skipped"
            )
        # 探测编码（源不可解析在此抛 ValueError → failed，锚点回退用原始 key）
        codec = _probe_codec(data)
        # 已是浏览器友好编码 + faststart：原始对象直接可播，预览 key 指向原始 key
        if codec in media_probe.BROWSER_FRIENDLY_CODECS and media_probe.has_faststart(
            data
        ):
            mark_succeeded(
                session,
                job,
                {
                    "object_key": object_key,
                    "preview_key": object_key,
                    "transcode": False,
                    "codec": codec,
                },
            )
            session.commit()
            return

        preview_bytes, _meta = media_probe.transcode_preview(data)
        stem = Path(object_key).stem or "video"
        preview_key = f"processed/{weld_id}/video/{stem}.preview.mp4"
        storage.upload_stream(
            preview_key, io.BytesIO(preview_bytes), len(preview_bytes), "video/mp4"
        )
        mark_succeeded(
            session,
            job,
            {
                "object_key": object_key,
                "preview_key": preview_key,
                "transcode": True,
                "codec": codec,
            },
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001 - 自捕获：写 failed 后正常返回
        logger.opt(exception=True).warning(
            "media_prep failed: object_key={} err={}", object_key, exc
        )
        session.rollback()  # 事务脏则回滚，避免 commit 失败
        fresh = session.get(Job, job.id)
        if fresh is not None:
            mark_failed(session, fresh, {"message": str(exc)})
            session.commit()


def _probe_codec(data: bytes) -> str | None:
    """探测源视频编码（ffmpeg -i stderr → `Video: <codec>`），不可解析抛 ValueError。"""
    import subprocess
    import tempfile
    from pathlib import Path

    ff = media_probe.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.mp4"
        path.write_bytes(data)
        proc = subprocess.run(
            [str(ff), "-i", str(path)], capture_output=True, timeout=30
        )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    info = media_probe.parse_ffmpeg_info(stderr)
    if info["duration"] is None:
        raise ValueError(f"Unable to parse video metadata (ffmpeg exit code {proc.returncode})")
    return info["codec"]


@register_handler("media_prep")
def handle(job_id: int, session: Session) -> None:
    """executor 入口：按 job id 取任务 → run_media_prep。"""
    job = session.get(Job, job_id)
    if job is None:
        return
    run_media_prep(session, job)
