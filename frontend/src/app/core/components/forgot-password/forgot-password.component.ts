import { Component } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from 'src/app/services/api.service';
import { ToastService } from '../../services/toast.service';
import { AuthService } from '../../auth/auth-service.service';
import { RedirectService } from '../../services/redirect.service';

@Component({
  standalone: false,
  selector: 'app-forgot-password',
  templateUrl: './forgot-password.component.html',
  styleUrls: ['./forgot-password.component.scss']
})
export class ForgotPasswordComponent {

  formNoPwd : UntypedFormGroup;
  private email: UntypedFormControl;
  public disableSubmit = false;
  

  constructor (
    public _authService: AuthService,
    private redirect: RedirectService,
    private _toastService: ToastService,
    private api: ApiService,
    private router: Router
  ) {
    this.email = new UntypedFormControl(null, [Validators.required, Validators.email]);

    this.formNoPwd = new UntypedFormGroup({});

    this.formNoPwd.addControl('email', this.email)
  }
  resetPwdRequest() {
    if (this.formNoPwd.invalid) {
      this.formNoPwd.markAllAsTouched();
      return;
    }
    // La réinitialisation passe par la plateforme et non par Keycloak : celle de
    // Keycloak n'écrirait que de son côté, et l'ancien mot de passe resterait
    // valable sur les applications qui lisent la base historique.
    this.disableSubmit = true;
    this.api.requestPasswordReset(this.formNoPwd.value.email).subscribe({
      next: () => {
        this._toastService.info(
          'Si un compte existe pour cette adresse, vous allez recevoir un lien de réinitialisation.',
          'Réinitialisation'
        );
        this.router.navigate(['/']);
      },
      error: () => {
        this.disableSubmit = false;
        this._toastService.error(
          'Demande impossible pour le moment. Réessayez dans quelques minutes.',
          'Réinitialisation'
        );
      },
    });
  }
}
