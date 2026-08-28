/**
 * src/api/files.ts — 文件存储（§3.7 / §4.2）。
 *
 * - `uploadFile`：小文件（<100MB）代理上传，multipart `file` 字段。FormData 直接作
 *   body 交给 client 透传（不设 Content-Type，浏览器自动带 boundary）。fetch 无原生
 *   上传进度，完成后回调 100 供 UI 收尾。
 * - `getFileUrl`：object_key 含 `/`（如 `uploads/<uuid>/x.mp4`），路径按 `:path`
 *   捕获，**不**对整串 encodeURIComponent（否则 `/` 变 `%2F` 不匹配路由）。
 * - `putFileDirect`：XHR 直传预签名 PUT URL（fetch 无上传进度，XHR 有），
 *   供 Registration 提交时把锚定文件直传 MinIO（跳过后端代理，实测吞吐 ~2×）。
 */
import { request } from './client';

/** 小文件代理上传到 MinIO，返回对象键 + 可播放/下载的预签名 URL。 */
export async function uploadFile(
  file: File,
  onProgress?: (p: number) => void,
): Promise<{ object_key: string; url: string }> {
  const form = new FormData();
  form.append('file', file);
  const data = await request<{ object_key: string; url: string }>(
    '/files/upload',
    { method: 'POST', body: form },
  );
  onProgress?.(100);
  return data;
}

/** 大文件预签名直传（≥100MB、≤2GB）：返回对象键 + 可 PUT 的 upload_url。 */
export async function presignUpload(req: {
  size: number;
  content_type: string;
  prefix: string;
  filename?: string;
}): Promise<{ object_key: string; upload_url: string }> {
  return request<{ object_key: string; upload_url: string }>(
    '/files/presign-upload',
    { method: 'POST', body: req },
  );
}

/**
 * 用 XHR 把文件直传到预签名 PUT URL（fetch 无上传进度，XHR 有）。
 * MinIO 已放行 CORS（OPTIONS 预检反射 Origin），浏览器跨域 PUT 可用。
 */
export function putFileDirect(
  uploadUrl: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', uploadUrl);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`直传失败：HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('直传失败：网络错误'));
    xhr.send(file);
  });
}

/** 预签名下载/播放 URL（支持 Range 拖动播放）。expires 秒，缺省 3600、上限 86400。 */
export async function getFileUrl(
  objectKey: string,
  expires?: number,
): Promise<{ url: string }> {
  return request<{ url: string }>(`/files/${objectKey}/url`, {
    query: { expires },
  });
}
