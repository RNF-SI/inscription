import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';

import { ApiService } from './api.service';
import { environment } from 'src/environments/environment';

describe('ApiService', () => {
  let service: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
    });
    service = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
  });

  it('loads applications catalog', () => {
    service.getApplications().subscribe((apps) => {
      expect(apps.length).toBe(1);
      expect(apps[0].slug).toBe('ancrage');
    });
    const req = http.expectOne(`${environment.apiUrl}/applications/`);
    expect(req.request.method).toBe('GET');
    req.flush([{ slug: 'ancrage', nom: 'Ancrage', url: '', image: '', description: '', managed_by_si: true, requires_access_request: true }]);
  });

  it('creates admin application', () => {
    const payload = {
      slug: 'new-app',
      nom: 'New',
      managed_by_si: true,
      requires_access_request: true,
    };
    service.createAdminApplication(payload).subscribe((app) => {
      expect(app.slug).toBe('new-app');
    });
    const req = http.expectOne(`${environment.apiUrl}/admin/catalog/applications/`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);
    req.flush({ ...payload, url: '', image: '', description: '' });
  });

  it('updates user application access', () => {
    service.updateUserApplicationAccess('user-sub', { waterwise: true }).subscribe();
    const req = http.expectOne(`${environment.apiUrl}/admin/users/user-sub/application-access/`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ access: { waterwise: true } });
    req.flush({ user: {}, applications: [] });
  });
});
