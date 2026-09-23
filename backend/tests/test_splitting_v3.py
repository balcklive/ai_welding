"""分段 v3 纯函数测试（不连 DB）：唯一窗口算法 / 多模态映射 / 预览令牌。

覆盖设计 §6.1 的无副作用组件与 §3.2/§3.3 的口径：

- `build_time_windows`：唯一窗口算法（`1 + (总采样点-窗口采样点)//步长采样点`）、
  默认 2.0/2.0、重叠、尾片 `drop`/`keep`、越界与非法参数一律报错；
- `map_window_to_modalities`：各模态引用由**映射**派生（帧号含 offset、图片像素按弧长投影）、
  模态越界记 `available=false` + reason 而不伪造；
- `preview_token`：HMAC 签名（改一个字节就失效）、过期、格式错；
- `rules_hash` / `mapping_hash`：稳定且对内容敏感——它们是"所见即所得"的比对依据。
"""

from __future__ import annotations

import time

import pytest

from app.services import splitting


# ── 唯一的窗口算法 ───────────────────────────────────────────────────


def _windows(**kwargs):
    params = {
        "duration": 100.0, "sample_rate": 1000,
        "window_seconds": 2.0, "stride_seconds": 2.0, "event_bounds": (0.0, 100.0),
    }
    params.update(kwargs)
    return splitting.build_time_windows(**params)


def test_default_windows_are_two_seconds_and_non_overlapping() -> None:
    """默认 2.0/2.0（§2.3）：50 个不重叠窗口，相邻半开区间无缝无重叠。"""
    windows = _windows()
    assert len(windows) == 50
    assert windows[0].start == 0.0 and windows[0].end == 2.0
    assert windows[1].start == 2.0 and windows[1].end == 4.0
    assert windows[-1].start == 98.0 and windows[-1].end == 100.0
    for prev, nxt in zip(windows, windows[1:]):
        assert prev.end == nxt.start, "相邻窗口必须首尾相接，无缝隙"


def test_overlap_is_reported_by_stride() -> None:
    """步长 < 时长即重叠：1.5/0.5 → 每步前进 0.5，窗口之间重叠 1.0 秒。"""
    windows = _windows(window_seconds=1.5, stride_seconds=0.5, event_bounds=(0.0, 10.0))
    assert len(windows) == 18  # 1 + (10000 - 1500) // 500
    assert windows[0].start == 0.0 and windows[0].end == 1.5
    assert windows[1].start == 0.5 and windows[1].end == 2.0
    assert windows[1].start < windows[0].end, "步长小于时长时相邻窗口必须重叠"


def test_tail_drop_is_the_default_and_keep_adds_one_uneven_window() -> None:
    """尾片默认丢弃（§2.3）；`keep` 才保留一个截到 E_end 的不等长窗口。"""
    dropped = _windows(event_bounds=(0.0, 5.0))
    assert [w.duration for w in dropped] == [2.0, 2.0]  # 第 3 个窗口只放得下 1 秒 → 丢

    kept = _windows(event_bounds=(0.0, 5.0), tail_policy="keep")
    assert len(kept) == len(dropped) + 1
    assert kept[-1].start == 4.0 and kept[-1].end == 5.0
    assert kept[-1].duration == pytest.approx(1.0), "尾片是不等长的"


def test_tail_keep_does_not_duplicate_a_full_window() -> None:
    """刚好整除时 `keep` 不该多出一个零长尾片。"""
    dropped = _windows(event_bounds=(0.0, 6.0))
    kept = _windows(event_bounds=(0.0, 6.0), tail_policy="keep")
    assert len(kept) == len(dropped) == 3


def test_sample_indices_are_ceil_derived_from_seconds() -> None:
    """采样点是**派生**信息：设计 §3.2 规定按 `ceil(秒 × 采样率)` 取整。"""
    windows = _windows(sample_rate=3, window_seconds=2.0, stride_seconds=2.0, event_bounds=(0.0, 4.0))
    assert (windows[0].frame_start, windows[0].frame_end) == (0, 6)   # ceil(0)=0, ceil(6)=6
    assert (windows[1].frame_start, windows[1].frame_end) == (6, 12)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_seconds": 0.0},
        {"stride_seconds": 0.0},
        {"event_bounds": (5.0, 5.0)},          # end <= start
        {"event_bounds": (-1.0, 10.0)},        # 起点为负
        {"event_bounds": (0.0, 200.0)},        # 超出真实时长
        {"event_bounds": (0.0, 1.0)},          # 有效区间短于一个窗口
    ],
)
def test_invalid_rule_inputs_raise(kwargs) -> None:
    with pytest.raises(splitting.SplitInputError):
        _windows(**kwargs)


def test_validate_rules_normalizes_and_rejects() -> None:
    assert splitting.validate_rules(window_seconds="2", stride_seconds=2, tail_policy="drop") == (2.0, 2.0, "drop")
    with pytest.raises(splitting.SplitInputError):
        splitting.validate_rules(window_seconds=None, stride_seconds=2, tail_policy="drop")
    with pytest.raises(splitting.SplitInputError):
        splitting.validate_rules(window_seconds=float("nan"), stride_seconds=2, tail_policy="drop")
    with pytest.raises(splitting.SplitInputError):
        splitting.validate_rules(window_seconds=2, stride_seconds=2, tail_policy="whatever")


# ── 多模态映射（§3.3） ───────────────────────────────────────────────


def _mapping(*, offset: float = 0.5, calibrated: bool = True, roi: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "unified_axis": {"unit": "second", "origin": "signal_first_sample", "duration": 100.0},
        "event_bounds": {"start": 0.0, "end": 100.0},
        "mappings": {
            "timeseries": {"type": "identity", "available": True, "calibrated": True, "reason": None},
            "video": {
                "type": "linear", "available": True, "calibrated": calibrated,
                "offset_seconds": offset, "fps": 25.0, "duration": 99.0, "reason": None,
            },
            "seam_image": {
                "type": "arc_length", "available": True, "calibrated": roi is not None,
                "object_key": "raw/REG/seam.jpg", "roi": roi,
                "speed_source": "channel" if roi else None,
                "arc_profile": [[0.0, 0.0], [100.0, 1.0]],
                "reason": None if roi else "焊缝图片未框选 ROI",
            },
            "audio": {"type": "none", "available": False, "calibrated": False, "reason": "源未附加"},
        },
    }


def _window(index: int = 1, start: float = 8.0, end: float = 10.0) -> splitting.SplitWindow:
    return splitting._window(index, start, end, 1000, end - start)


def test_video_frames_apply_offset() -> None:
    """`t_video = t_signal - offset`（§3.1.1）：offset=0.5 时 8.0s 对应视频 7.5s。"""
    video = splitting.map_window_to_modalities(
        _window(), mapping=_mapping(offset=0.5), sample_rate=1000, weld_id="W", version_id=1
    )["video"]
    assert video["available"] is True
    assert video["offset_seconds"] == 0.5
    assert video["start_frame"] == 188  # ceil((8.0 - 0.5) * 25)
    assert video["end_frame"] == 238    # ceil((10.0 - 0.5) * 25)


def test_video_negative_offset_shifts_the_other_way() -> None:
    """offset 为负（视频早于信号开始）时帧号向前移——符号写反会系统性错位。"""
    video = splitting.map_window_to_modalities(
        _window(), mapping=_mapping(offset=-1.0), sample_rate=1000, weld_id="W", version_id=1
    )["video"]
    assert video["start_frame"] == 225  # ceil((8.0 + 1.0) * 25)


def test_video_window_outside_coverage_is_unavailable_not_faked() -> None:
    """整段落在视频覆盖范围之外 → `available=false` + reason，**不伪造帧号**（§3.2 末段）。"""
    video = splitting.map_window_to_modalities(
        _window(start=200.0, end=202.0), mapping=_mapping(), sample_rate=1000,
        weld_id="W", version_id=1,
    )["video"]
    assert video["available"] is False
    assert "覆盖范围" in video["reason"]


def test_video_partial_overlap_clamps_start_frame_to_zero() -> None:
    """部分重叠时把起点钳到 0，不记不存在的负帧号。"""
    video = splitting.map_window_to_modalities(
        _window(start=0.0, end=1.0), mapping=_mapping(offset=0.6), sample_rate=1000,
        weld_id="W", version_id=1,
    )["video"]
    assert video["available"] is True
    assert video["start_frame"] == 0


def test_video_keyframes_stay_inside_coverage() -> None:
    """首/中/末三帧只保留换算后确实在覆盖范围内的——抽不到的帧不该出现在 manifest 里。"""
    video = splitting.map_window_to_modalities(
        _window(start=8.0, end=10.0), mapping=_mapping(offset=0.5), sample_rate=1000,
        weld_id="W", version_id=1,
    )["video"]
    assert [k["at"] for k in video["keyframes"]] == [8.0, 9.0, 9.96]


def test_seam_image_projects_by_arc_length() -> None:
    """`px(t) = roi.x + r(t) × roi.w`（§3.1.2）：线性折线下 8–10s 投影到 ROI 的 8%–10%。"""
    seam = splitting.map_window_to_modalities(
        _window(start=8.0, end=10.0),
        mapping=_mapping(roi={"x": 100.0, "y": 0.0, "w": 1000.0, "h": 50.0}),
        sample_rate=1000, weld_id="W", version_id=1,
    )["seam_image"]
    assert seam["available"] is True
    assert seam["spatial_range"]["start_px"] == pytest.approx(180.0)
    assert seam["spatial_range"]["end_px"] == pytest.approx(200.0)


def test_seam_image_without_roi_is_unavailable_with_reason() -> None:
    seam = splitting.map_window_to_modalities(
        _window(), mapping=_mapping(roi=None), sample_rate=1000, weld_id="W", version_id=1
    )["seam_image"]
    assert seam["available"] is False
    assert "ROI" in seam["reason"]


def test_signal_part_carries_derived_sample_indices() -> None:
    signal = splitting.map_window_to_modalities(
        _window(start=8.0, end=10.0), mapping=_mapping(), sample_rate=1000, weld_id="W", version_id=1
    )["signal"]
    assert signal["available"] is True and signal["start_index"] == 8000 and signal["end_index"] == 10000
    assert signal["sample_rate"] == 1000


def test_manifest_declares_schema_version_and_mapping_hash() -> None:
    manifest = splitting.map_window_to_modalities(
        _window(), mapping=_mapping(), sample_rate=1000, weld_id="WLD-1", version_id=7
    )
    assert manifest["schema_version"] == 3
    assert manifest["time_range"] == {"start": 8.0, "end": 10.0, "duration": 2.0}
    assert manifest["source"] == {
        "weld_id": "WLD-1", "version_id": 7, "mapping_hash": splitting.mapping_hash(_mapping()),
    }
    assert manifest["audio"]["available"] is False


# ── 预览令牌 ─────────────────────────────────────────────────────────


def test_preview_token_roundtrip_and_tamper_detection() -> None:
    token = splitting.sign_preview_token({"weld_id": "W", "version_id": 1, "expires_at": time.time() + 60})
    assert token.startswith("spv_")
    payload = splitting.verify_preview_token(token)
    assert payload["weld_id"] == "W" and payload["version_id"] == 1

    # 改一个字节签名即失效（不能靠"客户端自己改规则"绕过所见即所得）
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(splitting.SplitInputError):
        splitting.verify_preview_token(tampered)


def test_preview_token_rejects_expired_and_malformed() -> None:
    expired = splitting.sign_preview_token({"weld_id": "W", "expires_at": time.time() - 1})
    with pytest.raises(splitting.SplitInputError):
        splitting.verify_preview_token(expired)
    for bad in ("", "nope", "spv_not-base64.at-all", None):
        with pytest.raises(splitting.SplitInputError):
            splitting.verify_preview_token(bad)  # type: ignore[arg-type]


def test_hashes_are_stable_and_content_sensitive() -> None:
    """哈希是"预览 == 产物"的比对依据：内容不变则稳定，变一点就变。"""
    rules = {"window_seconds": 2.0, "stride_seconds": 2.0, "tail_policy": "drop"}
    assert splitting.rules_hash(rules) == splitting.rules_hash(dict(rules))
    assert splitting.rules_hash(rules) != splitting.rules_hash({**rules, "window_seconds": 1.5})

    mapping = _mapping()
    assert splitting.mapping_hash(mapping) == splitting.mapping_hash(_mapping())
    assert splitting.mapping_hash(mapping) != splitting.mapping_hash(_mapping(offset=1.5))
    assert splitting.mapping_hash(None) == splitting.mapping_hash({})


# ── 逐段代表帧的换算（预览与产物共用同一处） ─────────────────────────


def test_representative_frame_is_window_midpoint_on_signal_axis() -> None:
    """代表帧默认取**本段窗口中点**（信号轴），不是首帧、也不是全局某一帧。"""
    _m, video = _mapping().get("mappings"), _mapping()["mappings"]["video"]
    window = _window(3, start=8.0, end=10.0)
    assert splitting.representative_frame_time(window, video) == 9.0

    part = splitting.map_window_to_modalities(
        window, mapping=_mapping(), sample_rate=1000, weld_id="W", version_id=1
    )["video"]["frame"]
    assert part["available"] is True
    assert part["t_signal"] == 9.0
    assert part["t_video"] == 8.5, "t_video = t_signal - offset（offset=0.5）"
    assert part["frame_no"] == 212, "帧号 = t_video × fps（25 fps）"


def test_representative_frame_time_is_none_outside_video_coverage() -> None:
    """中点落到视频覆盖范围外 → None（调用方据此记"本段没有代表帧"+原因），不钳到端点。"""
    video = _mapping(offset=0.5)["mappings"]["video"]
    # 视频覆盖视频轴 [0, 99)，即信号轴 [0.5, 99.5)
    assert splitting.representative_frame_time(_window(1, start=0.0, end=0.4), video) is None
    assert splitting.representative_frame_time(_window(1, start=100.0, end=102.0), video) is None
    assert splitting.representative_frame_time(_window(1, start=98.0, end=100.0), video) is not None


def test_representative_frame_time_needs_usable_video() -> None:
    """视频不可用 / 没有帧率 → 没有代表帧（宁可不给，也不猜一个时刻去抽帧）。"""
    window = _window(1, start=8.0, end=10.0)
    assert splitting.representative_frame_time(window, {"available": False}) is None
    assert splitting.representative_frame_time(
        window, {"available": True, "fps": None, "duration": 99.0}
    ) is None
    assert splitting.representative_frame_time(
        window, {"available": True, "fps": 0, "duration": 99.0}
    ) is None


def test_video_part_always_carries_a_frame_reason_when_unavailable() -> None:
    """每一段都要能回答"为什么没有代表帧"——不可用分支也带 `frame.reason`。"""
    unavailable = splitting.map_window_to_modalities(
        _window(1, start=8.0, end=10.0),
        mapping={**_mapping(), "mappings": {**_mapping()["mappings"],
                                            "video": {"available": False, "reason": "无可用视频文件"}}},
        sample_rate=1000, weld_id="W", version_id=1,
    )["video"]
    assert unavailable["frame"]["available"] is False
    assert unavailable["frame"]["reason"] == "无可用视频文件"
