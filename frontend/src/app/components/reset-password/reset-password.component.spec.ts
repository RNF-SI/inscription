import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';

import { ResetPasswordComponent } from './reset-password.component';
import { RegisterService } from 'src/app/services/register.service';
import { ToastService } from 'src/app/core/services/toast.service';

describe('ResetPasswordComponent', () => {
  let component: ResetPasswordComponent;
  let fixture: ComponentFixture<ResetPasswordComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ResetPasswordComponent],
      imports: [ReactiveFormsModule, MatTooltipModule],
      providers: [
        {
          // Le constructeur lit le jeton dans l'URL ; une valeur non numérique
          // déclencherait une redirection vers l'accueil.
          provide: ActivatedRoute,
          useValue: { queryParams: of({ token: '42' }) },
        },
        { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
        { provide: RegisterService, useValue: { passwordChange: () => of({ msg: '' }) } },
        { provide: ToastService, useValue: { info: () => undefined, error: () => undefined } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ResetPasswordComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('reads the reset token from the query string', () => {
    expect(component.token).toBe('42');
  });
});
