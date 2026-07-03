import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { HomeComponent } from './home.component';
import { ApiService } from 'src/app/services/api.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { ToastrService } from 'ngx-toastr';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

describe('HomeComponent', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [HomeComponent],
      providers: [
        {
          provide: ApiService,
          useValue: {
            getApplications: () =>
              of([
                {
                  slug: 'ancrage',
                  nom: 'Ancrage',
                  url: 'https://example.org',
                  image: 'ancrage.png',
                  description: 'Desc',
                  managed_by_si: true,
                  requires_access_request: true,
                },
              ]),
          },
        },
        {
          provide: AuthService,
          useValue: {
            getMeSnapshot: () => null,
            getUser: () => of(null),
          },
        },
        { provide: ToastrService, useValue: { success: () => undefined, error: () => undefined } },
        { provide: NgbModal, useValue: { open: () => ({}) } },
      ],
    }).compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(HomeComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('loads applications on init', () => {
    expect(component.applicationsLoading).toBeFalse();
    expect(component.applications.length).toBe(1);
    expect(component.applications[0].slug).toBe('ancrage');
  });

  it('builds application image url via helper', () => {
    expect(component.applicationImageUrl('ancrage.png')).toContain('ancrage.png');
  });

  it('filters applications by management and access', () => {
    spyOnProperty(component, 'user', 'get').and.returnValue({} as never);
    component.applications = [
      {
        slug: 'si-active',
        nom: 'SI active',
        url: '',
        image: '',
        description: '',
        managed_by_si: true,
        requires_access_request: true,
        access_status: 'active',
      },
      {
        slug: 'si-none',
        nom: 'SI none',
        url: '',
        image: '',
        description: '',
        managed_by_si: true,
        requires_access_request: true,
        access_status: 'none',
      },
      {
        slug: 'indep',
        nom: 'Indep',
        url: '',
        image: '',
        description: '',
        managed_by_si: false,
        requires_access_request: false,
        access_status: 'none',
      },
    ];

    component.setManagementFilter('si');
    expect(component.filteredApplications.map((app) => app.slug)).toEqual(['si-active', 'si-none']);

    component.setAccessFilter('with_access');
    expect(component.filteredApplications.map((app) => app.slug)).toEqual(['si-active']);

    component.resetApplicationFilters();
    expect(component.filteredApplications.length).toBe(3);
  });
});
