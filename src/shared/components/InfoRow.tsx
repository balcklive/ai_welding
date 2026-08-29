export function InfoRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="info-row">
      <span>{label}</span>
      <strong className={accent ? 'accent-text' : ''}>{value}</strong>
    </div>
  );
}
