export const formatDateTime = (iso: string | null | undefined): string =>
  iso ? iso.replace('T', ' ').slice(0, 16) : '—';
