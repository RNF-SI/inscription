import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
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

  constructor(
    private fb: UntypedFormBuilder,
    private api: ApiService,
    private auth: AuthService,
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
