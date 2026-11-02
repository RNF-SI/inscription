import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { of, throwError } from 'rxjs';

import { MoncompteComponent } from './moncompte.component';
import { ApiService, MeResponse } from 'src/app/services/api.service';
import { AuthService } from 'src/app/core/auth/auth-service.service';
import { ToastService } from 'src/app/core/services/toast.service';

function faireMe(profil: Partial<MeResponse['profile']>): MeResponse {
  return {
    profile: {
      keycloak_sub: 'sub-1',
      email: 'paul@example.org',
      username: 'paul.lesiak',
      first_name: 'Paul',
      last_name: 'Lesiak',
      is_super_admin: false,
      legacy_id_role: 42,
      ...profil,
    },
    applications: [],
    reserves: [],
    is_app_admin: false,
    unread_notifications: 0,
  };
}

describe('MoncompteComponent', () => {
  let component: MoncompteComponent;
  let fixture: ComponentFixture<MoncompteComponent>;
  let api: { getMe: jasmine.Spy; getMyReserveOptions: jasmine.Spy; updateMe: jasmine.Spy };

  beforeEach(async () => {
    api = {
      getMe: jasmine.createSpy('getMe').and.returnValue(of(faireMe({}))),
      getMyReserveOptions: jasmine.createSpy('getMyReserveOptions').and.returnValue(of([])),
      updateMe: jasmine.createSpy('updateMe').and.returnValue(of(null)),
    };

    await TestBed.configureTestingModule({
      declarations: [MoncompteComponent],
      // Le gabarit s'appuie sur [formGroup], [(ngModel)] et <mat-spinner>.
      imports: [FormsModule, ReactiveFormsModule, MatProgressSpinnerModule],
      providers: [
        { provide: ApiService, useValue: api },
        {
          provide: AuthService,
          useValue: {
            getMeSnapshot: () => null,
            restoreSession: () => of(false),
            refreshAccessToken: () => of(true),
          },
        },
        { provide: ToastService, useValue: { success: () => {}, error: () => {} } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MoncompteComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('identifiant', () => {
    /**
     * Les comptes que l'import a dû renommer portent deux identifiants : celui des
     * applications historiques et celui de Keycloak. « Mon compte » affiche
     * l'ancien, celui que l'usager connaît et qui sert partout ailleurs.
     */
    it('affiche l’identifiant historique plutôt que celui de Keycloak', () => {
      component['applyMe'](
        faireMe({ username: 'paul.lesiak', legacy_username: 'Paul Lesiak', username_diverges: true }),
      );
      expect(component.identifiantAffiche).toBe('Paul Lesiak');
      expect(component.identifiantKeycloak).toBe('paul.lesiak');
      expect(component.identifiantARegulariser).toBeTrue();
    });

    it('retombe sur l’identifiant Keycloak quand il n’y a pas d’historique', () => {
      component['applyMe'](faireMe({ legacy_username: '' }));
      expect(component.identifiantAffiche).toBe('paul.lesiak');
      expect(component.identifiantARegulariser).toBeFalse();
    });

    it('refuse un identifiant non conforme sans appeler l’API', () => {
      component['applyMe'](faireMe({ legacy_username: 'Paul Lesiak', username_diverges: true }));
      component.edit();
      component.form.patchValue({ identifiant: 'Paul Lesiak' });

      component.save();

      expect(api.updateMe).not.toHaveBeenCalled();
      expect(component.form.get('identifiant')?.invalid).toBeTrue();
    });

    it('transmet le nouvel identifiant en minuscules', () => {
      api.updateMe.and.returnValue(of(faireMe({})));
      component['applyMe'](faireMe({ legacy_username: 'Paul Lesiak', username_diverges: true }));
      component.edit();
      component.form.patchValue({ identifiant: 'Paul.Lesiak2' });

      component.save();

      expect(api.updateMe).toHaveBeenCalled();
      expect(api.updateMe.calls.mostRecent().args[0].username).toBe('paul.lesiak2');
    });

    it('ne transmet pas l’identifiant quand il n’a pas changé', () => {
      // Sinon un profil dont l'identifiant historique n'est pas conforme serait
      // refusé à chaque modification de nom ou d'adresse.
      api.updateMe.and.returnValue(of(faireMe({})));
      component['applyMe'](faireMe({ legacy_username: 'paul.lesiak' }));
      component.edit();
      component.form.patchValue({ nom_role: 'Lesiak-Martin' });

      component.save();

      expect(api.updateMe).toHaveBeenCalled();
      expect(api.updateMe.calls.mostRecent().args[0].username).toBeUndefined();
    });

    it('affiche le motif quand l’identifiant est déjà pris', () => {
      api.updateMe.and.returnValue(
        throwError(() => ({ status: 409, error: { detail: 'Cet identifiant est déjà utilisé.' } })),
      );
      component['applyMe'](faireMe({ legacy_username: 'Paul Lesiak', username_diverges: true }));
      component.edit();
      component.form.patchValue({ identifiant: 'deja.pris' });

      component.save();

      expect(component.saveError).toBe('Cet identifiant est déjà utilisé.');
      expect(component.saving).toBeFalse();
    });
  });
});
