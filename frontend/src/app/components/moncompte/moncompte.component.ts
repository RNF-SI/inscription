import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { AuthService } from 'src/app/core/auth/auth-service.service';
import { ToastService } from 'src/app/core/services/toast.service';
import { ApiService, MeResponse, ReserveOptionDto } from 'src/app/services/api.service';
import { catchError, finalize } from 'rxjs/operators';
import { of } from 'rxjs';

/** L'identifiant historique s'il est connu, celui de Keycloak sinon. */
function identifiantDe(me: MeResponse): string {
  return me.profile.legacy_username || me.profile.username || '';
}

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
  saveError = '';

  constructor(
    private fb: UntypedFormBuilder,
    private api: ApiService,
    private auth: AuthService,
    private toast: ToastService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    this.form = this.fb.group({
      // Les comptes que l'import a dû renommer portent deux identifiants : celui
      // des applications historiques et celui de Keycloak. Le champ sert à en
      // choisir un conforme, écrit des deux côtés, qui réconcilie les deux mondes.
      // Les majuscules sont acceptées puis repliées à l'enregistrement, parce que
      // Keycloak replie de son côté et que les deux mondes doivent recevoir la
      // même valeur.
      identifiant: ['', [Validators.required, Validators.minLength(3), Validators.pattern(/^[A-Za-z0-9._-]+$/)]],
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
    this.saveError = '';
    if (this.me) {
      this.patchFormFromMe(this.me);
    }
  }

  cancel(): void {
    this.isEditing = false;
    this.saveError = '';
    this.selectedReserveToAdd = '';
    if (this.me) {
      this.patchFormFromMe(this.me);
    }
  }

  save(): void {
    if (this.saving) {
      return;
    }
    this.saveError = '';
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const identifiant = (v.identifiant || '').trim().toLowerCase();
    const payload: Parameters<ApiService['updateMe']>[0] = {
      first_name: (v.prenom_role || '').trim(),
      last_name: (v.nom_role || '').trim(),
      email: (v.email || '').trim(),
      fonction: (v.fonction || '').trim(),
    };
    // Transmis seulement s'il change : sinon un profil dont l'identifiant
    // historique n'est pas conforme serait refusé à chaque modification de nom.
    if (identifiant && identifiant !== this.identifiantAffiche.toLowerCase()) {
      payload.username = identifiant;
    }
    this.saving = true;
    this.api.updateMe(payload).subscribe({
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
      error: (err) => {
        // 409 : identifiant déjà pris. Le reste reste générique.
        this.saveError =
          err?.error?.detail ||
          err?.error?.username?.[0] ||
          'Enregistrement impossible.';
        this.saving = false;
        this.cdr.detectChanges();
      },
    });
  }

  /** Identifiant à afficher : celui que connaissent les applications historiques. */
  get identifiantAffiche(): string {
    return this.me ? identifiantDe(this.me) : '';
  }

  /** Vrai tant que l'usager n'a pas choisi un identifiant valable des deux côtés. */
  get identifiantARegulariser(): boolean {
    return !!this.me?.profile?.username_diverges;
  }

  get identifiantKeycloak(): string {
    return this.me?.profile?.username || '';
  }

  private patchFormFromMe(me: MeResponse): void {
    const p = me.profile;
    this.form.patchValue({
      identifiant: identifiantDe(me),
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
