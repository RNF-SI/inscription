import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatGridListModule } from '@angular/material/grid-list';
import { RouterTestingModule } from '@angular/router/testing';
import { FontAwesomeModule } from '@fortawesome/angular-fontawesome';
import { of } from 'rxjs';

import { HomeComponent } from './home.component';
import { ApiService } from 'src/app/services/api.service';
import { AuthService } from 'src/app/core/auth/auth-service.service';
import { ToastService } from 'src/app/core/services/toast.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { LoadingSpinnerComponent } from 'src/app/core/components/loading-spinner/loading-spinner.component';

describe('HomeComponent', () => {
  let component: HomeComponent;
  let fixture: ComponentFixture<HomeComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [HomeComponent, LoadingSpinnerComponent],
      // La grille d'applications utilise les cartes et la grille Material,
      // les icones FontAwesome et [(ngModel)] pour les filtres.
      imports: [
        FormsModule,
        RouterTestingModule,
        MatCardModule,
        MatGridListModule,
        FontAwesomeModule,
      ],
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
            restoreSession: () => of(false),
            refreshMeFromApi: () => of(null),
            // Lu par le getter `user`, donc a chaque detection de changements.
            getCurrentUser: () => null,
          },
        },
        {
          provide: ToastService,
          useValue: {
            success: () => undefined,
            error: () => undefined,
            warning: () => undefined,
            info: () => undefined,
          },
        },
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
