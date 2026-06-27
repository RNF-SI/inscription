import { environment } from 'src/environments/environment';

const UI_ASSET_IMAGES = new Set(['embleme.png', 'embleme.svg', 'banierre.jpg', 'fond.png']);

function apiOrigin(): string {
  return environment.apiUrl.replace(/\/api\/?$/, '');
}

/** URL publique d'une vignette application (dossier media Django). */
export function applicationImageUrl(filename?: string, cacheBust?: number): string {
  const name = (filename || '').trim();
  if (!name) {
    return '';
  }
  if (UI_ASSET_IMAGES.has(name)) {
    const url = `/assets/images/${name}`;
    return cacheBust ? `${url}?v=${cacheBust}` : url;
  }
  const url = `${apiOrigin()}/media/application-images/${encodeURIComponent(name)}`;
  return cacheBust ? `${url}?v=${cacheBust}` : url;
}
