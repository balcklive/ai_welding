import { useState } from 'react';

interface TextDialogProps {
  title: string;
  label: string;
  initialValue?: string;
  /**
   * 可选：追加一个下拉选择字段（如「新建数据集」的任务类型，取值来自系统设置字典）。
   * 给出后 `onConfirm(value, choiceLabel)` 的第二参为该选择值。
   */
  choice?: { label: string; initialValue?: string; options: { value: string; label: string }[] };
  onCancel: () => void;
  onConfirm: (value: string, choice?: string) => void;
}

export function TextDialog({ title, label, initialValue = '', choice, onCancel, onConfirm }: TextDialogProps) {
  const [value, setValue] = useState(initialValue);
  const [choiceValue, setChoiceValue] = useState(choice?.initialValue ?? choice?.options[0]?.value ?? '');
  return (
    <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}>
      <div className="app-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="app-dialog-head"><h2>{title}</h2><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div>
        <label>{label}<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); if (event.key === 'Enter' && value.trim()) onConfirm(value.trim(), choice ? choiceValue : undefined); }} /></label>
        {choice && <label className="dialog-choice">{choice.label}<select value={choiceValue} onChange={(event) => setChoiceValue(event.target.value)}>{choice.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
        <div className="app-dialog-actions"><button className="outline-button" onClick={onCancel}>取消</button><button className="primary-button" disabled={!value.trim() || (!!choice && !choiceValue)} onClick={() => onConfirm(value.trim(), choice ? choiceValue : undefined)}>确认</button></div>
      </div>
    </div>
  );
}
