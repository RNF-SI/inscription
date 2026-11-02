import { applicationImageUrl } from './application-image.util';

describe('applicationImageUrl', () => {
  it('returns empty string for blank filename', () => {
    expect(applicationImageUrl('')).toBe('');
    expect(applicationImageUrl(undefined)).toBe('');
  });

  it('serves UI assets from /assets/images', () => {
    expect(applicationImageUrl('embleme.svg')).toBe('/assets/images/embleme.svg');
    expect(applicationImageUrl('banierre.jpg', 42)).toBe('/assets/images/banierre.jpg?v=42');
  });

  it('serves application images from Django media', () => {
    const url = applicationImageUrl('ancrage.png');
    expect(url).toContain('/media/application-images/ancrage.png');
    expect(applicationImageUrl('ancrage.png', 99)).toContain('?v=99');
  });
});
