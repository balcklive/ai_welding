import { useEffect, useMemo, useRef } from 'react';
import { Annotorious, ImageAnnotator, useAnnotator, useAnnotations } from '@annotorious/react';
import type { ImageAnnotation, ImageAnnotator as AnnotatorInstance } from '@annotorious/annotorious';
import '@annotorious/react/annotorious-react.css';

/**
 * 开源依赖来源说明（便于升级、改造和问题追踪）：
 *
 * - Annotorious 核心项目：Annotorious / annotorious
 *   GitHub：https://github.com/annotorious/annotorious
 *   官方文档：https://annotorious.dev/
 * - 本项目使用的 React 适配包：@annotorious/react
 *   npm：https://www.npmjs.com/package/@annotorious/react
 * - 当前验证版本：@annotorious/annotorious 3.8.9、@annotorious/react 3.8.9
 *   版本由 package.json 与 package-lock.json 共同锁定；升级时需同步验证矩形框、
 *   多边形、已有标注回显以及 onChange 保存链路。
 *
 * 本文件是平台内部适配层：负责把后端的 box/polygon 标注模型转换为
 * Annotorious ImageAnnotation，再转换回平台 LabelItem；不要直接修改 node_modules。
 */

export type ImageEditorTool = 'rectangle' | 'polygon';

export interface ImageEditorAnnotation {
  id: string;
  category: string;
  kind: 'box' | 'polygon';
  box: number[];
  points: number[][];
}

interface Props {
  src: string;
  annotations: ImageEditorAnnotation[];
  tool: ImageEditorTool;
  defaultLabel: string;
  onChange: (annotations: ImageEditorAnnotation[]) => void;
}

function boundsFromPoints(points: number[][]) {
  const xs = points.map((point) => point[0] ?? 0);
  const ys = points.map((point) => point[1] ?? 0);
  return { minX: Math.min(...xs, 0), minY: Math.min(...ys, 0), maxX: Math.max(...xs, 0), maxY: Math.max(...ys, 0) };
}

function toAnnotoriousAnnotation(annotation: ImageEditorAnnotation): ImageAnnotation {
  const id = annotation.id || `local-${crypto.randomUUID()}`;
  const selector = annotation.kind === 'polygon'
    ? { type: 'POLYGON' as const, geometry: { points: annotation.points, bounds: boundsFromPoints(annotation.points) } }
    : { type: 'RECTANGLE' as const, geometry: { x: annotation.box[0] ?? 0, y: annotation.box[1] ?? 0, w: annotation.box[2] ?? 0, h: annotation.box[3] ?? 0, bounds: { minX: annotation.box[0] ?? 0, minY: annotation.box[1] ?? 0, maxX: (annotation.box[0] ?? 0) + (annotation.box[2] ?? 0), maxY: (annotation.box[1] ?? 0) + (annotation.box[3] ?? 0) } } };
  return { id, target: { annotation: id, selector }, bodies: [{ id: `${id}-label`, annotation: id, purpose: 'tagging', value: annotation.category }] } as ImageAnnotation;
}

function fromAnnotorious(annotation: ImageAnnotation, fallbackLabel: string): ImageEditorAnnotation | null {
  const selector = annotation.target?.selector;
  const category = annotation.bodies?.find((body) => body.purpose === 'tagging')?.value ?? fallbackLabel;
  if (!selector || !('geometry' in selector)) return null;
  if (selector.type === 'RECTANGLE') {
    const geometry = selector.geometry as unknown as { x: number; y: number; w: number; h: number };
    return { id: annotation.id, category, kind: 'box', box: [geometry.x, geometry.y, geometry.w, geometry.h], points: [] };
  }
  if (selector.type === 'POLYGON') {
    const geometry = selector.geometry as unknown as { points: number[][] };
    return { id: annotation.id, category, kind: 'polygon', box: [], points: geometry.points };
  }
  return null;
}

function AnnotationBridge({ initial, tool, defaultLabel, onChange }: { initial: ImageAnnotation[]; tool: ImageEditorTool; defaultLabel: string; onChange: (annotations: ImageEditorAnnotation[]) => void }) {
  const anno = useAnnotator<AnnotatorInstance<ImageAnnotation>>();
  const annotations = useAnnotations<ImageAnnotation>(40);
  const initializedRef = useRef(false);
  const lastSignatureRef = useRef('');

  useEffect(() => {
    if (!anno || initializedRef.current) return;
    anno.setAnnotations(initial, true);
    initializedRef.current = true;
  }, [anno, initial]);

  useEffect(() => { if (anno) anno.setDrawingTool(tool); }, [anno, tool]);

  useEffect(() => {
    if (!anno) return;
    const addDefaultBody = (annotation: ImageAnnotation) => {
      if (annotation.bodies?.some((body) => body.purpose === 'tagging')) return;
      anno.state.store.addBody({ id: `${annotation.id}-label`, annotation: annotation.id, purpose: 'tagging', value: defaultLabel });
    };
    anno.on('createAnnotation', addDefaultBody);
    return () => anno.off('createAnnotation', addDefaultBody);
  }, [anno, defaultLabel]);

  useEffect(() => {
    const next = annotations.flatMap((annotation) => { const converted = fromAnnotorious(annotation, defaultLabel); return converted ? [converted] : []; });
    const signature = JSON.stringify(next);
    if (signature === lastSignatureRef.current) return;
    lastSignatureRef.current = signature;
    onChange(next);
  }, [annotations, defaultLabel, onChange]);

  return null;
}

export function AnnotoriousImageEditor({ src, annotations, tool, defaultLabel, onChange }: Props) {
  const initial = useMemo(() => annotations.map(toAnnotoriousAnnotation), [annotations]);
  return <div className="annotorious-image-editor"><Annotorious><ImageAnnotator tool={tool} drawingMode="drag" containerClassName="annotorious-image-layer"><img src={src} alt="待标注图片" /></ImageAnnotator><AnnotationBridge initial={initial} tool={tool} defaultLabel={defaultLabel} onChange={onChange} /></Annotorious></div>;
}
