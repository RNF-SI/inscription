import { Component } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
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
    private router: Router
  ) {
    this.email = new UntypedFormControl(null, [Validators.required, Validators.email]);

    this.formNoPwd = new UntypedFormGroup({});

    this.formNoPwd.addControl('email', this.email)
  }
  resetPwdRequest() {
    this._authService.loginOrPwdRecovery(this.formNoPwd.value).subscribe(() => {
      this._toastService.info(
        'Utilisez la page Keycloak qui s’ouvre pour réinitialiser votre mot de passe.',
        'Réinitialisation'
      );
      this.router.navigate(['/']);
    });
  }
}
