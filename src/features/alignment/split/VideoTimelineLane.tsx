/**
 * 视频帧轨（设计 §4.4）：**一段一格**的胶片条。
 *
 * 每格是本段自己的代表帧（`w.video.frame.url`，服务端按窗口中点抽的真帧），格宽即该段
 * 在时间轴上的占比——相邻两格的分界线就是切片边界，所以这条轨回答的是"切成了几段、
 * 每段长什么样"，和下方卡片网格是同一件事的两种入口（点格子 = 选段）。
 *
 * **曾经的写法是一个 `<video>` 播放器 + 80 个"缩略图时间点"标记**：屏幕上只有一个画面
 * 加一堆等距竖线，看起来像"对一张图在分段"。播放器已挪到选中切片详情面板——那里才是
 * "把某一段播出来看看"的地方，一条轨只表达一件事。
 *
 * 帧一律用服务端给的地址；取不到就如实给原因（视频不可用 / 覆盖范围外 / 抽帧失败都由
 * 服务端给），不拿别的段或全局首帧顶替。`frame_no`/`t_video` 同理，前端不自己换算。
 */
import { Play } from 'lucide-react';
import type { SplitPreviewWindow } from '../../../api/types';
import { pctOf } from './splitTypes';

interface Props {
  windows: SplitPreviewWindow[];
  duration: number;
  calibrated: boolean;
  reason: string | null;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

export function VideoTimelineLane({
  windows, duration, calibrated, reason, selectedIndex, onSelect,
}: Props) {
  // 一段真帧都没有（视频不可用 / 全都抽不到）→ 整条轨走空态，而不是画一排空格子
  const ready = windows.some((w) => w.video.frame?.url);
  return (
    <div className="lane lane-video">
      <div className="lane-label">
        <i className="lane-dot" style={{ background: '#2c9caf' }} />
        视频帧
        <span className={`track-availability ${calibrated ? 'ok' : 'warn'}`}>
          {calibrated ? '已标定' : '未标定'}
        </span>
      </div>
      <div className="lane-track lane-track-film">
        {ready ? (
          windows.map((w) => {
            const left = pctOf(w.start, duration);
            const width = Math.max(0, pctOf(w.end, duration) - left);
            const frame = w.video.frame;
            const missing = frame?.reason ?? w.video.reason ?? '视频不可用';
            return (
              <button
                type="button"
                key={w.index}
                className={`film-cell${w.index === selectedIndex ? ' is-selected' : ''}`}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={frame?.url ? `分段 #${w.index} 的视频代表帧` : `分段 #${w.index} 无代表帧：${missing}`}
                aria-label={`选择分段 #${w.index}`}
                aria-pressed={w.index === selectedIndex}
                onClick={() => onSelect(w.index)}
              >
                {frame?.url ? (
                  <img src={frame.url} alt={`分段 #${w.index} 的视频代表帧`} loading="lazy" />
                ) : (
                  // 无帧的格子走浅底（不是深色占位——深底看着像一帧画面）
                  <span className="film-cell-empty" aria-hidden>无帧</span>
                )}
              </button>
            );
          })
        ) : (
          <div className="lane-video-empty">
            <Play size={18} />
            <span>{reason ?? '等待真实视频'}</span>
          </div>
        )}
      </div>
      <small className="lane-note">
        一格 = 一个分段，格内是本段窗口中点的真帧，格宽即该段时长；点格子选中该段。
      </small>
    </div>
  );
}
