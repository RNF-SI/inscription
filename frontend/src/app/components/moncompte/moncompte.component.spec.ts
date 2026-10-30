import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { of } from 'rxjs';

import { MoncompteComponent } from './moncompte.component';
import { ApiService } from 'src/app/services/api.service';
import { AuthService } from 'src/app/core/auth/auth-service.service';

describe('MoncompteComponent', () => {
  let component: MoncompteComponent;
  let fixture: ComponentFixture<MoncompteComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [MoncompteComponent],
      // Le gabarit s'appuie sur [formGroup], [(ngModel)] et <mat-spinner>.
      imports: [FormsModule, ReactiveFormsModule, MatProgressSpinnerModule],
      providers: [
        {
          // getMe() sans profil : le composant reste sur son état vide.
          provide: ApiService,
          useValue: {
            getMe: () => of(null),
            getMyReserveOptions: () => of([]),
          },
        },
        {
          provide: AuthService,
          useValue: {
            getMeSnapshot: () => null,
            restoreSession: () => of(false),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(MoncompteComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
