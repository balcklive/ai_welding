/**
 * react-image-annotate 无自带 TS 类型（peer 仅 React 16，--legacy-peer-deps 安装）。
 * 本项目只用其图像模式做多边形标注（非受控组件：`images` 喂图 + `onExit` 取回 regions），
 * props 按最小可用子集放宽为 any；points 为归一化坐标（0~1，相对图像自然尺寸），
 * 落库前乘以帧宽高转像素。
 */
declare module 'react-image-annotate' {
  import * as React from 'react';
  const ImageAnnotate: React.FC<{
    images?: Array<{ src: string; regions?: unknown[] }>;
    videoSrc?: string;
    enabledTools?: string[];
    selectedTool?: string;
    regionClsList?: string[];
    regionTagList?: string[];
    hideHeader?: boolean;
    hideNext?: boolean;
    hidePrev?: boolean;
    onExit?: (state: { images?: Array<{ regions?: unknown[] }> }) => void;
    [key: string]: unknown;
  }>;
  export default ImageAnnotate;
}
