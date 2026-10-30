import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { AuthService } from 'src/app/core/auth/auth-service.service';
import { ToastService } from 'src/app/core/services/toast.service';
import { ApiService, MeResponse, ReserveOptionDto } from 'src/app/services/api.service';
import { catchError, finalize } from 'rxjs/operators';
import { of } from 'rxjs';

@Component({
  standalone: false,
  selector: 'app-moncompte',
  templateUrl: './moncompte.component.html',
  styleUrls: ['./moncompte.component.scss'],
})
export class MoncompteComponent implements OnInit {
  form: UntypedFormGroup;
  me: MeResponse | null = null;
  saving = false;
  isEditing = false;
  reserveOptions: ReserveOptionDto[] = [];
  selectedReserveToAdd = '';
  addingReserve = false;
  removingReserveCode: string | null = null;
  referentSavingCode: string | null = null;
  passwordForm: UntypedFormGroup;
  changingPassword = false;
  passwordError = '';

  constructor(
    private fb: UntypedFormBuilder,
    private api: ApiService,
    private auth: AuthService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.form = this.fb.group({
      identifiant: [{ value: '', disabled: true }],
      nom_role: [''],
      prenom_role: [''],
      fonction: [''],
      organisme: [{ value: '', disabled: true }],
      email: [''],
    });

    this.passwordForm = this.fb.group({
      current_password: ['', [Validators.required]],
      new_password: ['', [Validators.required, Validators.minLength(8)]],
      new_password_confirmation: ['', [Validators.required]],
    });

    const cached = this.auth.getMeSnapshot();
    if (cached) {
      this.applyMe(cached);
    }

    this.auth
      .restoreSession()
      .pipe(catchError(() => of(false)))
      .subscribe(() => {
        this.loadMe();
      });
  }

  private applyMe(me: MeResponse): void {
    this.me = me;
    localStorage.setItem('me_snapshot', JSON.stringify(me));
    this.patchFormFromMe(me);
    this.cdr.detectChanges();
  }

  private loadMe(): void {
    this.api
      .getMe()
      .pipe(
        catchError(() => of(null)),
        finalize(() => this.cdr.detectChanges()),
      )
      .subscribe((me) => {
        if (me) {
          this.applyMe(me);
          this.loadReserveOptions();
        }
      });
  }

  edit(): void {
    this.isEditing = true;
    if (this.me) {
      this.patchFormFromMe(this.me);
    }
  }

  cancel(): void {
    this.isEditing = false;
    this.selectedReserveToAdd = '';
    if (this.me) {
      this.patchFormFromMe(this.me);
    }
  }

  save(): void {
    if (this.saving) {
      return;
    }
    const v = this.form.getRawValue();
    this.saving = true;
    this.api.updateMe({
      first_name: (v.prenom_role || '').trim(),
      last_name: (v.nom_role || '').trim(),
      email: (v.email || '').trim(),
      fonction: (v.fonction || '').trim(),
    }).subscribe({
      next: () => {
        this.auth.refreshAccessToken().subscribe({
          next: () => {
            this.api.getMe().subscribe({
              next: (me) => {
                this.applyMe(me);
                this.isEditing = false;
              },
              complete: () => {
                this.saving = false;
                this.cdr.detectChanges();
              },
              error: () => {
                this.saving = false;
                this.cdr.detectChanges();
              },
            });
          },
          error: () => {
            this.saving = false;
          },
        });
      },
      error: () => {
        this.saving = false;
      },
    });
  }

  private patchFormFromMe(me: MeResponse): void {
    const p = me.profile;
    this.form.patchValue({
      identifiant: p.username || '',
      nom_role: p.last_name || '',
      prenom_role: p.first_name || '',
      fonction: p.fonction || '',
      organisme: p.organisme || '',
      email: p.email || '',
    });
  }

  get currentReserves() {
    return this.me?.reserves || [];
  }

  get availableReserveOptions() {
    const currentCodes = new Set(this.currentReserves.map((r) => r.area_code));
    return this.reserveOptions.filter((r) => !currentCodes.has(r.area_code));
  }

  addReserve(): void {
    const code = (this.selectedReserveToAdd || '').trim();
    if (!code || this.addingReserve || this.removingReserveCode || this.referentSavingCode) {
      return;
    }
    this.addingReserve = true;
    this.api.addMyReserve(code).subscribe({
      next: () => this.refreshAfterReserveChange(),
      error: () => {
        this.addingReserve = false;
      },
    });
  }

  removeReserve(areaCode: string): void {
    if (!areaCode || this.removingReserveCode || this.addingReserve || this.referentSavingCode) {
      return;
    }
    this.removingReserveCode = areaCode;
    this.api.removeMyReserve(areaCode).subscribe({
      next: () => this.refreshAfterReserveChange(),
      error: () => {
        this.removingReserveCode = null;
      },
    });
  }

  requestReferent(areaCode: string): void {
    if (!areaCode || this.referentSavingCode || this.addingReserve || this.removingReserveCode) {
      return;
    }
    this.referentSavingCode = areaCode;
    this.api.requestMyReserveReferent(areaCode).subscribe({
      next: () => this.refreshAfterReserveChange(),
      error: () => {
        this.referentSavingCode = null;
      },
    });
  }

  changePassword(): void {
    this.passwordError = '';
    if (this.passwordForm.invalid) {
      this.passwordForm.markAllAsTouched();
      return;
    }
    const data = this.passwordForm.value;
    if (data.new_password !== data.new_password_confirmation) {
      this.passwordError = 'Les deux saisies ne correspondent pas.';
      return;
    }
    this.changingPassword = true;
    this.api
      .changeMyPassword(data)
      .pipe(
        finalize(() => {
          this.changingPassword = false;
          this.cdr.detectChanges();
        }),
      )
      .subscribe({
        next: () => {
          this.passwordForm.reset();
          this.toast.success(
            'Il est actif sur toutes les plateformes RNF.',
            'Mot de passe modifié',
          );
        },
        error: (err) => {
          // Le backend renvoie un motif exploitable : mot de passe actuel faux,
          // compte géré par l'annuaire, ou refus de la politique du realm.
          this.passwordError = err?.error?.detail || 'Changement de mot de passe impossible.';
        },
      });
  }

  private loadReserveOptions(): void {
    this.api.getMyReserveOptions().subscribe({
      next: (opts) => {
        this.reserveOptions = opts || [];
        this.cdr.detectChanges();
      },
      error: () => {
        this.reserveOptions = [];
        this.cdr.detectChanges();
      },
    });
  }

  private refreshAfterReserveChange(): void {
    this.auth.refreshAccessToken().subscribe({
      next: () => {
        this.api.getMe().subscribe({
          next: (me) => {
            this.applyMe(me);
            this.selectedReserveToAdd = '';
            this.loadReserveOptions();
          },
          complete: () => {
            this.addingReserve = false;
            this.removingReserveCode = null;
            this.referentSavingCode = null;
            this.cdr.detectChanges();
          },
          error: () => {
            this.addingReserve = false;
            this.removingReserveCode = null;
            this.referentSavingCode = null;
            this.cdr.detectChanges();
          },
        });
      },
      error: () => {
        this.addingReserve = false;
        this.removingReserveCode = null;
        this.referentSavingCode = null;
      },
    });
  }
}
