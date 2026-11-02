import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDividerModule } from '@angular/material/divider';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { RouterTestingModule } from '@angular/router/testing';
import { NgMultiSelectDropDownModule } from 'ng-multiselect-dropdown';
import { NgxMatSelectSearchModule } from 'ngx-mat-select-search';
import { of } from 'rxjs';

import { SignUpComponent } from './sign-up.component';
import { RegisterService } from 'src/app/services/register.service';
import { ToastService } from 'src/app/core/services/toast.service';

describe('SignUpComponent', () => {
  let component: SignUpComponent;
  let fixture: ComponentFixture<SignUpComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [SignUpComponent],
      // Le formulaire d'inscription tire sur une bonne partie des modules
      // déclarés par AppModule : sélecteurs Material, recherche et réserves.
      imports: [
        NoopAnimationsModule,
        FormsModule,
        ReactiveFormsModule,
        RouterTestingModule,
        MatButtonModule,
        MatDividerModule,
        MatIconModule,
        MatSelectModule,
        MatTooltipModule,
        NgxMatSelectSearchModule,
        NgMultiSelectDropDownModule.forRoot(),
      ],
      providers: [
        {
          provide: RegisterService,
          useValue: {
            getOrganismes: () => of([]),
            getApplications: () => of([]),
            getOrganisme: () => of(null),
          },
        },
        {
          provide: ToastService,
          useValue: { error: () => undefined, info: () => undefined },
        },
      ],
    }).compileComponents();
  });

  beforeEach(() => {
    fixture = TestBed.createComponent(SignUpComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
