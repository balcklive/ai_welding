import { BarChart3, Database, TrainFront, Waves } from 'lucide-react';

export type Route =
  | 'overview'
  | 'data-center/datasets'
  | 'data-center/registration'
  | 'data-center/validation'
  | 'data-center/versions'
  | 'analysis/select'
  | 'analysis/alignment'
  | 'analysis/analysis'
  | 'analysis/split'
  | 'analysis/annotation'
  | 'analysis/features'
  | 'model-center/dataset-build'
  | 'model-center/repository'
  | 'model-center/training'
  | 'model-center/testing'
  | 'model-center/inference';

export const workspaceHeaders: Record<string, { eyebrow: string; title: string; description: string }> = {
  'data-center': { eyebrow: '数据资产中心', title: '数据管理', description: '以单条焊缝数据为单位，管理数据登记、质量核验和版本链路。' },
  analysis: { eyebrow: '多模态数据生产线', title: '分析与标注', description: '选择一条焊缝后，完成对齐、起收弧识别、切分与标注。' },
  'model-center': { eyebrow: '模型研发中心', title: '模型中心', description: '从数据到模型：准备训练数据，统一管理模型版本、训练任务、测试评估与推理验证。' },
};

export const navStructure: {
  id: string;
  label: string;
  icon: typeof BarChart3;
  route?: Route;
  children?: { route: Route; label: string }[];
}[] = [
  { id: 'overview', label: '数据总览', icon: BarChart3, route: 'overview' },
  { id: 'data-center', label: '数据管理', icon: Database, route: 'data-center/datasets', children: [
    { route: 'data-center/datasets', label: '数据集' },
    { route: 'data-center/registration', label: '数据登记' },
    { route: 'data-center/validation', label: '数据核验' },
    { route: 'data-center/versions', label: '焊缝版本' },
  ] },
  { id: 'analysis', label: '分析与标注', icon: Waves, children: [
    { route: 'analysis/select', label: '选择数据' },
    { route: 'analysis/alignment', label: '多模态对齐' },
    { route: 'analysis/analysis', label: '起收弧识别' },
    { route: 'analysis/split', label: '样本分段' },
    { route: 'analysis/annotation', label: '数据标注' },
    { route: 'analysis/features', label: '特征提取' },
  ] },
  { id: 'model-center', label: '模型中心', icon: TrainFront, children: [
    { route: 'model-center/dataset-build', label: '训练数据准备' },
    { route: 'model-center/repository', label: '模型资产' },
    { route: 'model-center/training', label: '新建训练' },
    { route: 'model-center/testing', label: '测试评估' },
    { route: 'model-center/inference', label: '推理验证' },
  ] },
];
