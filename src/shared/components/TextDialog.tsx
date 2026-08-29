import { useState } from 'react';

interface TextDialogProps {
  title: string;
  label: string;
  initialValue?: string;
  onCancel: () => void;
  onConfirm: (value: string) => void;
}

export function TextDialog({ title, label, initialValue = '', onCancel, onConfirm }: TextDialogProps) {
  const [value, setValue] = useState(initialValue);
  return (
    <div className="app-dialog-backdrop" role="presentation" onClick={onCancel}>
      <div className="app-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <div className="app-dialog-head"><h2>{title}</h2><button className="icon-button" onClick={onCancel} aria-label="关闭">×</button></div>
        <label>{label}<input autoFocus value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); if (event.key === 'Enter' && value.trim()) onConfirm(value.trim()); }} /></label>
        <div className="app-dialog-actions"><button className="outline-button" onClick={onCancel}>取消</button><button className="primary-button" disabled={!value.trim()} onClick={() => onConfirm(value.trim())}>确认</button></div>
      </div>
    </div>
  );
}
