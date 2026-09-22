"""对齐坐标映射单元测试（不连 DB）：统一坐标系 + 视频/焊缝图片映射 + 焊接速度三级降级。

覆盖 `docs/多模态时间统一样本分段重构设计方案.md` §9.2 的验收标准：

- offset 符号（`t_unified = t_video + offset`）；
- 弧长积分（速度非恒定处 r(t) 必须偏离时间比例）；
- 焊接速度三级降级（channel / scalar / none）；
- ROI 形状校验；
- `aligned = available && calibrated`——**未标定不得声称已对齐**。

纯函数测试，与 `test_media_probe.py` 同一套路（不连 DB、不连存储）。
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services import alignment
from app.services.signals import Channel, SignalBundle

FS = 10
DURATION = 10.0
BOUNDS = (0.0, 10.0)


def _channel(channel_id: str, values: list[float]) -> Channel:
    arr = np.asarray(values, dtype=float)
    return Channel(
        id=channel_id, name=channel_id, unit="", values=arr,
        lo=float(arr.min()), hi=float(arr.max()), mean=float(arr.mean()),
    )


def _bundle(weld_speed: list[float] | None = None) -> SignalBundle:
    """最小可用 bundle：恒有核心通道 cur；weld_speed 存在时额外加一根通道。"""
    channels = [_channel("cur", [0.0] * int(DURATION * FS))]
    if weld_speed is not None:
        channels.append(_channel("weld_speed", weld_speed))
    return SignalBundle(
        weld_id="WLD-TEST-0001",
        duration=DURATION,
        sample_rate=FS,
        channels=channels,
        events={"arc": 0.0, "weld_segment": list(BOUNDS), "tail": 10.0},
        source="real",
    )


def _events() -> dict:
    return {"arc": 0.0, "weld_segment": list(BOUNDS), "tail": 10.0}


# ── position_ratio_at ───────────────────────────────────────────────


def test_position_ratio_interpolates_between_points() -> None:
    profile = [[0.0, 0.0], [10.0, 1.0]]
    assert alignment.position_ratio_at(profile, 5.0) == pytest.approx(0.5)
    assert alignment.position_ratio_at(profile, 2.5) == pytest.approx(0.25)


def test_position_ratio_clamps_outside_range_without_extrapolating() -> None:
    """区间外钳制到端点：越界窗口按「该模态缺失」处理，不能外推出 r<0 或 r>1。"""
    profile = [[2.0, 0.0], [8.0, 1.0]]
    assert alignment.position_ratio_at(profile, 0.0) == 0.0
    assert alignment.position_ratio_at(profile, 99.0) == 1.0
    assert alignment.position_ratio_at([], 5.0) == 0.0


# ── arc_length_profile：三级降级 ─────────────────────────────────────


def test_arc_length_constant_channel_speed_matches_time_ratio() -> None:
    """恒定焊接速度下，弧长比例退化为时间比例（积分与线性一致）。"""
    source, profile = alignment.arc_length_profile(
        _bundle([3.0] * int(DURATION * FS)), BOUNDS, has_scalar_speed=True
    )
    assert source == "channel"
    assert alignment.position_ratio_at(profile, 0.0) == pytest.approx(0.0)
    assert alignment.position_ratio_at(profile, 5.0) == pytest.approx(0.5, abs=0.02)
    assert alignment.position_ratio_at(profile, 10.0) == pytest.approx(1.0)


def test_arc_length_varying_channel_speed_deviates_from_time_ratio() -> None:
    """速度前快后慢：中点必须落在时间比例之后（走得更远），这正是积分存在的意义。"""
    half = int(DURATION * FS) // 2
    source, profile = alignment.arc_length_profile(
        _bundle([2.0] * half + [1.0] * half), BOUNDS, has_scalar_speed=True
    )
    assert source == "channel"
    mid = alignment.position_ratio_at(profile, 4.9)
    # 弧长：前 4.9s 走 2.0*4.9=9.8，总长 2.0*5+1.0*5=15 → 0.653
    assert mid == pytest.approx(9.8 / 15, abs=0.03)
    assert mid > 0.5  # 明显偏离时间比例


def test_arc_length_negative_speed_not_counted() -> None:
    """收弧回抽的负速度不计入弧长——焊缝不会倒退。"""
    half = int(DURATION * FS) // 2
    source, profile = alignment.arc_length_profile(
        _bundle([2.0] * half + [-5.0] * half), BOUNDS, has_scalar_speed=True
    )
    assert source == "channel"
    # 负速度段全部截为 0：后半程不前进
    assert alignment.position_ratio_at(profile, 5.0) == pytest.approx(1.0)


def test_arc_length_falls_back_to_scalar_then_none() -> None:
    """无 weld_speed 通道 → 恒速退化；scalar 与 none 折线相同，仅来源标注不同。"""
    bundle = _bundle(None)
    source_scalar, profile_scalar = alignment.arc_length_profile(
        bundle, BOUNDS, has_scalar_speed=True
    )
    source_none, profile_none = alignment.arc_length_profile(
        bundle, BOUNDS, has_scalar_speed=False
    )
    assert source_scalar == "scalar"
    assert source_none == "none"
    assert profile_scalar == profile_none == [[0.0, 0.0], [10.0, 1.0]]
    assert alignment.position_ratio_at(profile_none, 5.0) == pytest.approx(0.5)


def test_arc_length_all_zero_speed_falls_back() -> None:
    """通道在但全程零速（未起弧）→ 不能除零，退回恒速并如实标注。"""
    source, profile = alignment.arc_length_profile(
        _bundle([0.0] * int(DURATION * FS)), BOUNDS, has_scalar_speed=False
    )
    assert source == "none"
    assert alignment.position_ratio_at(profile, 5.0) == pytest.approx(0.5)


# ── ROI 形状校验 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "roi",
    [None, {}, {"x": 0, "y": 0, "w": 0, "h": 10}, {"x": 0, "y": 0, "w": -1, "h": 10},
     {"x": 0, "y": 0, "w": 10}, {"x": "a", "y": 0, "w": 10, "h": 10}],
)
def test_normalize_roi_rejects_invalid_shapes(roi) -> None:
    assert alignment._normalize_roi(roi) is None


def test_normalize_roi_accepts_valid_shape() -> None:
    assert alignment._normalize_roi({"x": 1, "y": 2, "w": 100, "h": 20}) == {
        "x": 1.0, "y": 2.0, "w": 100.0, "h": 20.0,
    }


# ── build_coordinate_mapping ────────────────────────────────────────


def _mapping(calibration=None, *, video=True, image=True) -> dict:
    return alignment.build_coordinate_mapping(
        bundle=_bundle(None),
        events=_events(),
        calibration=calibration,
        has_scalar_speed=False,
        video_key="raw/REG/v.mp4" if video else None,
        video_meta={"duration": 180.9, "fps": 30.0, "width": 1920, "height": 1080} if video else None,
        seam_image_key="raw/REG/202.jpg" if image else None,
    )


def test_mapping_timeseries_is_identity_and_always_aligned() -> None:
    ts = _mapping()["mappings"]["timeseries"]
    assert ts["type"] == "identity"
    assert ts["available"] is True and ts["calibrated"] is True


def test_mapping_video_unaligned_without_calibration() -> None:
    """核心回归：未标定 offset 时视频轨**不得**声称已对齐。"""
    video = _mapping()["mappings"]["video"]
    assert video["available"] is True
    assert video["calibrated"] is False
    assert video["offset_seconds"] == 0.0  # 仍给 0 供换算，但如实标记未标定
    assert "未标定" in video["reason"]


def test_mapping_video_calibrated_carries_offset() -> None:
    video = _mapping({"video": {"offset_seconds": -1.1}})["mappings"]["video"]
    assert video["calibrated"] is True
    assert video["offset_seconds"] == pytest.approx(-1.1)
    assert video["reason"] is None


def test_mapping_video_unavailable_when_no_file() -> None:
    video = _mapping(video=False)["mappings"]["video"]
    assert video["available"] is False and video["calibrated"] is False
    assert video["offset_seconds"] is None


def test_mapping_seam_image_calibrated_only_with_roi() -> None:
    uncalibrated = _mapping()["mappings"]["seam_image"]
    assert uncalibrated["available"] is True
    assert uncalibrated["calibrated"] is False
    assert uncalibrated["roi"] is None
    assert "未框选" in uncalibrated["reason"]

    calibrated = _mapping(
        {"seam_image": {"roi": {"x": 120, "y": 300, "w": 1706, "h": 260}}}
    )["mappings"]["seam_image"]
    assert calibrated["calibrated"] is True
    assert calibrated["roi"]["w"] == 1706.0
    assert calibrated["reason"] is None


def test_mapping_seam_image_carries_speed_source_and_profile() -> None:
    """无焊接速度数据时仍产出可用的纯比例折线，如实标注 speed_source=none。"""
    seam = _mapping()["mappings"]["seam_image"]
    assert seam["speed_source"] == "none"
    assert seam["arc_profile"] == [[0.0, 0.0], [10.0, 1.0]]


def test_mapping_axis_and_bounds_from_bundle() -> None:
    mapping = _mapping()
    assert mapping["unified_axis"] == {
        "unit": "second", "origin": "signal_first_sample", "duration": DURATION,
    }
    assert mapping["event_bounds"] == {"start": 0.0, "end": 10.0}


def test_mapping_is_json_serialisable() -> None:
    """映射要写进 mapping.json 与 JSON 列，不能带 numpy 标量。"""
    import json

    json.dumps(_mapping({"video": {"offset_seconds": 0.5},
                         "seam_image": {"roi": {"x": 1, "y": 2, "w": 3, "h": 4}}}))


# ── 模型列与迁移 0018 的一致性 ────────────────────────────────────────


@pytest.mark.parametrize(
    ("table", "column"),
    [("data_versions", "calibration"), ("alignment_tasks", "mapping")],
)
def test_migration_0018_columns_declared_as_json(table: str, column: str) -> None:
    """模型必须声明迁移 `0018` 加的两列且类型为 JSON。

    SQLite 测试走 `create_all`（读模型），线上走迁移（写 DDL）——两边漂移只会在部署时
    才炸。这里把"模型有没有这列、是不是 JSON"钉住。
    """
    from sqlalchemy import JSON as SAJSON
    from sqlmodel import SQLModel

    col = SQLModel.metadata.tables[table].columns[column]
    assert isinstance(col.type, SAJSON)
    assert col.nullable is True  # 纯 expand：老行无值，必须可空


# ── 标定校验 / 合并 / offset 取值 ────────────────────────────────────


def test_calibration_offset_positive_negative_and_unset() -> None:
    assert alignment.calibration_offset_seconds({"video": {"offset_seconds": 1.1}}) == 1.1
    assert alignment.calibration_offset_seconds({"video": {"offset_seconds": -1.1}}) == -1.1
    # 未标定 / 形状不对 → 0.0（= "视频与信号同零点"的旧假设，映射会如实记 calibrated=false）
    assert alignment.calibration_offset_seconds({}) == 0.0
    assert alignment.calibration_offset_seconds({"video": None}) == 0.0
    assert alignment.calibration_offset_seconds({"video": {"offset_seconds": True}}) == 0.0


def test_validate_patch_accepts_signed_offsets() -> None:
    assert alignment.validate_calibration_patch(
        {"video": {"offset_seconds": 2.5}}, image_size=None
    ) == {"video": {"offset_seconds": 2.5}}
    assert alignment.validate_calibration_patch(
        {"video": {"offset_seconds": -2.5}}, image_size=None
    ) == {"video": {"offset_seconds": -2.5}}
    assert alignment.validate_calibration_patch(
        {"video": {"offset_seconds": 0}}, image_size=None
    ) == {"video": {"offset_seconds": 0.0}}


@pytest.mark.parametrize(
    "payload",
    [
        {"video": {"offset_seconds": "1.0"}},
        {"video": {"offset_seconds": None}},
        {"video": {"offset_seconds": float("nan")}},
        {"video": {"offset_seconds": float("inf")}},
        {"video": {"offset_seconds": True}},
        {"video": {"offset_seconds": 100000.0}},  # 超手误护栏
        {"video": "不是对象"},
    ],
)
def test_validate_patch_rejects_bad_offset(payload) -> None:
    with pytest.raises(alignment.CalibrationError):
        alignment.validate_calibration_patch(payload, image_size=None)


def test_validate_patch_roi_requires_image_size() -> None:
    """核实不了的断言不该放行：拿不到图片宽高时拒绝 ROI。"""
    with pytest.raises(alignment.CalibrationError):
        alignment.validate_calibration_patch(
            {"seam_image": {"roi": {"x": 0, "y": 0, "w": 10, "h": 10}}}, image_size=None
        )


def test_validate_patch_roi_within_image_bounds() -> None:
    roi = {"x": 10, "y": 20, "w": 100, "h": 30}
    assert alignment.validate_calibration_patch(
        {"seam_image": {"roi": roi}}, image_size=(400, 120)
    ) == {"seam_image": {"roi": {"x": 10.0, "y": 20.0, "w": 100.0, "h": 30.0}}}


@pytest.mark.parametrize(
    "roi",
    [
        {"x": -1, "y": 0, "w": 10, "h": 10},          # 左越界
        {"x": 0, "y": -1, "w": 10, "h": 10},          # 上越界
        {"x": 395, "y": 0, "w": 10, "h": 10},         # x+w > 宽
        {"x": 0, "y": 115, "w": 10, "h": 10},         # y+h > 高
        {"x": 0, "y": 0, "w": 401, "h": 10},          # 宽超图
    ],
)
def test_validate_patch_rejects_roi_outside_image(roi) -> None:
    with pytest.raises(alignment.CalibrationError):
        alignment.validate_calibration_patch(
            {"seam_image": {"roi": roi}}, image_size=(400, 120)
        )


def test_validate_patch_roi_exactly_at_bounds_is_ok() -> None:
    """贴边是合法的：`x+w == width` 不越界。"""
    assert alignment.validate_calibration_patch(
        {"seam_image": {"roi": {"x": 0, "y": 0, "w": 400, "h": 120}}},
        image_size=(400, 120),
    )


def test_validate_patch_null_clears_group() -> None:
    assert alignment.validate_calibration_patch(
        {"video": None, "seam_image": None}, image_size=None
    ) == {"video": None, "seam_image": None}


def test_validate_patch_only_touches_given_groups() -> None:
    """合并语义：没给的组不出现在补丁里，调用方据此保留原值。"""
    assert alignment.validate_calibration_patch(
        {"video": {"offset_seconds": 1.0}}, image_size=None
    ) == {"video": {"offset_seconds": 1.0}}


def test_merge_calibration_updates_adds_and_clears() -> None:
    current = {"video": {"offset_seconds": 1.0}, "seam_image": {"roi": {"x": 1, "y": 2, "w": 3, "h": 4}}}
    # 只改 video → seam_image 原样保留
    assert alignment.merge_calibration(current, {"video": {"offset_seconds": 2.0}}) == {
        "video": {"offset_seconds": 2.0},
        "seam_image": {"roi": {"x": 1, "y": 2, "w": 3, "h": 4}},
    }
    # 显式 None → 清除该组
    assert alignment.merge_calibration(current, {"video": None}) == {
        "seam_image": {"roi": {"x": 1, "y": 2, "w": 3, "h": 4}}
    }
    # 空补丁 → 原样
    assert alignment.merge_calibration(current, {}) == current


def test_seam_image_key_skips_align_artifacts() -> None:
    """上次对齐产出的关键帧 JPG 不是焊缝照片，不能被选中当 ROI 底图。"""
    assert alignment.seam_image_key(
        ["processed/W/align/keyframes/arc.jpg", "raw/REG/seam.png"]
    ) == "raw/REG/seam.png"
    assert alignment.seam_image_key(["processed/W/align/keyframes/arc.jpg"]) is None
    assert alignment.seam_image_key(None) is None


def test_calibration_payload_shape_and_defaults() -> None:
    payload = alignment.calibration_payload(None, {})
    assert payload["anchored_version_id"] is None
    assert payload["video"] == {"offset_seconds": 0.0, "calibrated": False}
    assert payload["seam_image"] == {"roi": None, "calibrated": False, "object_key": None}


def test_calibration_payload_reflects_calibration() -> None:
    class _V:
        id = 7
        object_keys = ["raw/REG/seam.png"]

    calibration = {
        "video": {"offset_seconds": -1.5},
        "seam_image": {"roi": {"x": 1, "y": 2, "w": 3, "h": 4}},
    }
    payload = alignment.calibration_payload(_V(), calibration)
    assert payload["anchored_version_id"] == 7
    assert payload["video"] == {"offset_seconds": -1.5, "calibrated": True}
    assert payload["seam_image"]["calibrated"] is True
    assert payload["seam_image"]["object_key"] == "raw/REG/seam.png"
