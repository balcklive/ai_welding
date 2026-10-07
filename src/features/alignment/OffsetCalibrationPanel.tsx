/**
 * 视频零点偏移量（offset）标定面板（设计 §4.2 的「标定面板」另一半）。
 *
 * **全站只有这里能改视频零点**——分段页只读消费同一份标定。本面板承担三件事：
 * 1) **反向标定**：用户在播放器里拖到「画面刚起弧」那一帧，点一下按钮，系统按
 *    `offset = 起弧信号时刻 − 视频当前时刻` 反解（后端语义是 `t_video = t_signal − offset`，
 *    故反过来就是 `offset = t_signal − t_video`）。这是"不必猜数值"的唯一路径。
 * 2) **数值 + 滑块手填**：已知偏差（例如实测 1.1s）直接填，拖动即时更新读数。
 * 3) **时间戳对照**：同屏显示「视频当前帧 ↔ 换算后的信号时刻」与覆盖残差，
 *    让用户知道调得对不对。
 *
 * 状态归属**刻意与 `SeamRoiEditor` 不同**：ROI 的草稿可以关在面板内部（不影响视频），
 * 但 offset 的草稿必须**即时驱动父组件的 `<video>` seek**，所以草稿由父组件持有，
 * 本面板是**受控组件**：只显示 + 回调，不发任何网络请求（写入只有一个入口 = 父组件的
 * `handleSaveOffset` → `PUT …/calibration` 的 `video` 组）。
 *
 * 未标定（`calibrated=false`）时后端返回 `offset_seconds: 0.0`，即退回旧假设；
 * 界面必须如实说「按 0 计算」，并且说清**保存 0 也算已标定**（`aligned = available && calibrated`）。
 */
import { useEffect, useState } from 'react';
import { AlertTriangle, Check, Clock, Target, Trash2 } from 'lucide-react';
import { fmt } from '../analysis/signals/chartData';

interface Readout {
  /** 信号（统一轴）总时长，秒。 */
  signalDuration: number;
  /** `<video>` 元素自身的时长；未加载/未就绪 → null。 */
  videoDuration: number | null;
  /** 视频轴当前时刻（`<video>.currentTime`）。 */
  videoTime: number;
  /** 起弧时刻（**信号轴**秒）；无真实信号事件 → null。 */
  arcSignal: number | null;
}

interface Props {
  /** 服务端 `video.calibrated`。 */
  calibrated: boolean;
  /** 服务端已保存的偏移（未标定 → 0）。 */
  savedOffset: number;
  /** 未保存草稿；null = 无改动。 */
  draft: number | null;
  /** `draft ?? savedOffset`（seek 与读数都用它）。 */
  effectiveOffset: number;
  onDraft: (value: number | null) => void;
  /** 以视频当前帧对齐起弧（父组件读 `<video>.currentTime` 反解）。 */
  onReverse: () => void;
  onSave: () => void;
  /** 写 `{video: null}` 回到未标定。 */
  onClear: () => void;
  saving: boolean;
  error: string | null;
  notice: string | null;
  readout: Readout;
  /** 非 null = 此刻不能反向标定，内容是原因（作按钮说明）。 */
  reverseHint: string | null;
}

/** 覆盖残差超过这个秒数就提示"零点可能未对齐"（默认窗口 2s，0.5s = 四分之一窗）。 */
const RESIDUAL_TOLERANCE = 0.5;

const round2 = (v: number) => Math.round(v * 100) / 100;
/** 带符号的秒（偏移量正负都有意义，不能省符号）。 */
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)} s`;
/**
 * 时间码 `mm:ss.xx`。**负值必须自己带符号**——`fmt()` 是按"非负时间轴"写的：
 * `fmt(-5)` 会算成 `Math.floor(-5/60) === -1`、余数 `55`，渲染出 `-1:55.00` 这种鬼东西。
 * 换算是 `t_signal = t_video + offset`，offset 为负或超过视频位置时它**本来就会是负数**
 * （例如视频只拍到信号 5s 处、offset=-5 时，视频首帧对应的信号时刻就是 -5s），所以不能直接用 `fmt`。
 */
const timecode = (v: number) => {
  const n = round2(v);          // 先按显示精度取整：`-0.001` → `-0`，而 `-0 < 0` 为假，不会印出负号
  return `${n < 0 ? '-' : ''}${fmt(Math.abs(n))}`;
};

export function OffsetCalibrationPanel({
  calibrated, draft, effectiveOffset, onDraft, onReverse, onSave, onClear,
  saving, error, notice, readout, reverseHint,
}: Props) {
  const [text, setText] = useState(() => String(round2(effectiveOffset)));
  const [focused, setFocused] = useState(false);
  // 外部改值（滑块、反向标定、保存成功）同步回输入框；正在输入时不打断。
  // 失焦后 `focused` 转 false 会再同步一次——顺手把非法输入（如空串/`-`）还原成真值。
  useEffect(() => {
    if (!focused) setText(String(round2(effectiveOffset)));
  }, [effectiveOffset, focused]);

  const dirty = draft !== null;
  const { signalDuration, videoDuration, videoTime, arcSignal } = readout;
  const derivedSignalTime = videoTime + effectiveOffset;
  const reverseValue = arcSignal != null && videoDuration != null ? round2(arcSignal - videoTime) : null;
  // 信号时长还没读到时不算残差：`signalDuration = 0` 会把残差算成整个视频长度，
  // 横幅就会在加载期间闪一句"视频覆盖比信号短 18.00 s"的假警告。
  const residual = videoDuration != null && signalDuration > 0
    ? effectiveOffset + videoDuration - signalDuration
    : null;
  const residualOk = residual != null && Math.abs(residual) <= RESIDUAL_TOLERANCE;

  const commitText = (raw: string) => {
    setText(raw);
    // 输入中间态（空 / 只有符号或小数点）不当作 0——那会让用户打字时闪一下 0。
    if (!raw.trim() || raw === '-' || raw === '.' || raw === '-.') return;
    const value = Number(raw);
    if (Number.isFinite(value)) onDraft(round2(value));
  };

  return (
    <section className="panel">
      <div className="studio-head">
        <div>
          <span className="file-badge"><Clock size={14} />视频零点标定</span>
          <h2>把视频时间对到信号时间（分段页只读，改动只在这里生效）</h2>
        </div>
        <span className={`track-availability ${calibrated ? 'ok' : 'warn'}`}>
          {calibrated ? '已标定' : '未标定（按 0 计算）'}
        </span>
      </div>

      {error && (
        <div className="alignment-banner bad" role="alert"><AlertTriangle size={15} />{error}</div>
      )}
      {notice && (
        <div className="alignment-banner ok" role="status"><Check size={15} />{notice}</div>
      )}
      {residual != null && (
        <div className={`alignment-banner ${residualOk ? 'ok' : 'warn'}`} role="status">
          <AlertTriangle size={15} />
          {!calibrated && '当前按 offset = 0 计算；'}
          {residualOk
            ? `视频与信号时长吻合（覆盖残差 ${signed(round2(residual))}）`
            : `视频覆盖比信号${residual < 0 ? '短' : '长'} ${Math.abs(round2(residual)).toFixed(2)} s，零点可能未对齐`}
        </div>
      )}

      <p className="preview-summary">
        主操作在左边那条**胶片条**上：拖动它把视频的起点对到信号轴上（靠近起弧标记会吸上去）。
        这里的手填与按钮用于精确微调，以及"视频从焊缝中间开始录"这种磁吸表达不了的情况——
        在播放器里拖到「画面刚起弧」那一帧，再点「以当前帧对齐起弧」，系统按
        <b> offset = 起弧信号时刻 − 视频当前时刻 </b>反解。
      </p>

      <label className="split-field-label" htmlFor="offset-value">视频零点偏移（秒）</label>
      <input
        id="offset-value"
        className="split-control"
        type="number"
        step={0.01}
        inputMode="decimal"
        value={text}
        onChange={(e) => commitText(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      />

      <div className="seam-roi-meta">
        <span>信号时长：{signalDuration > 0 ? timecode(signalDuration) : '读取中…'}</span>
        <span>视频时长：{videoDuration != null ? timecode(videoDuration) : '未就绪'}</span>
        <span>视频当前帧 {timecode(videoTime)} ↔ 信号 {timecode(derivedSignalTime)}</span>
        <span>当前偏移：{signed(effectiveOffset)}</span>
        <span>按当前帧对齐起弧 ⇒ {reverseValue != null ? signed(reverseValue) : '—'}</span>
        {dirty && <span className="warning-text">有未保存的改动</span>}
      </div>

      <p className="preview-summary">
        {calibrated
          ? '已标定：换算按上面的偏移执行，改完记得保存并重新运行对齐任务。'
          : '未标定即所有换算按 offset = 0，可能与视频整体错位；保存后（哪怕保存的是 0）即记为已标定。'}
        「清除标定」把这一组清掉，回到未标定。
      </p>

      <button
        type="button"
        className="full-button"
        disabled={reverseHint !== null || saving}
        aria-disabled={reverseHint !== null || saving}
        title={reverseHint ?? '按 offset = 起弧信号时刻 − 视频当前时刻 反解'}
        onClick={onReverse}
      >
        <Target size={15} />以当前帧对齐起弧
      </button>
      <div className="split-action-row">
        <button
          type="button"
          className="full-button"
          disabled={!dirty || saving}
          aria-disabled={!dirty || saving}
          onClick={onSave}
        >
          {saving ? '保存中…' : '保存偏移量'}
        </button>
        <button
          type="button"
          className="full-button studio-reset"
          disabled={!calibrated || saving}
          aria-disabled={!calibrated || saving}
          onClick={onClear}
        >
          <Trash2 size={15} />清除标定
        </button>
      </div>
    </section>
  );
}
