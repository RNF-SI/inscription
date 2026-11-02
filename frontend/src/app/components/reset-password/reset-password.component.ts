import { Component } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from 'src/app/services/api.service';
import { ToastService } from 'src/app/core/services/toast.service';

@Component({
  standalone: false,
  selector: 'app-reset-password',
  templateUrl: './reset-password.component.html',
  styleUrls: ['./reset-password.component.scss']
})
export class ResetPasswordComponent {
  form: UntypedFormGroup;
  public disableSubmit = false;
  token: string;

  constructor(
    private fb: UntypedFormBuilder,
    private api: ApiService,
    private router: Router,
    private activatedRoute: ActivatedRoute,
    private _toastService: ToastService
  ) {
    this.activatedRoute.queryParams.subscribe((params) => {
      let token = params['token'];
      
      // Les jetons sont alphanumériques (secrets.token_urlsafe) : l'ancien
      // contrôle n'acceptait que des chiffres et renvoyait tout le monde à
      // l'accueil.
      if (!RegExp('^[A-Za-z0-9_-]{20,}$').test(token || '')) {
        this.router.navigate(['/']);
      }
      this.token = token;
    });
  }

  ngOnInit() {
    this.createForm();
  }

  save() {
    if (this.form.valid) {
      let data = this.form.value;
      this.disableSubmit = true;
      this.api
        .confirmPasswordReset({
          token: this.token,
          new_password: data['password'],
          new_password_confirmation: data['password_confirmation'],
        })
        .subscribe({
          next: () => {
            this._toastService.success(
              'Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.',
              'Mot de passe réinitialisé',
            );
            this.router.navigate(['/']);
          },
          error: (err) => {
            this.disableSubmit = false;
            // Le backend renvoie un motif exploitable : lien expiré, déjà utilisé,
            // ou refus de la politique de mot de passe.
            this._toastService.error(
              err?.error?.detail || 'Réinitialisation impossible.',
              'Mot de passe',
            );
          },
        });
    }
  }

  createForm() {
    this.form = this.fb.group({
      password: ['', [Validators.required]],
      password_confirmation: ['', [Validators.required]],
    },
    {
      validators: [
        this.ConfirmedValidator('password','password_confirmation')
      ]

    }
    );
  }

  ConfirmedValidator(controlName: string, matchingControlName: string) {
    return (formGroup: UntypedFormGroup) => {
      const control = formGroup.controls[controlName];
      const matchingControl = formGroup.controls[matchingControlName];
      if (
        matchingControl.errors &&
        !matchingControl.errors['confirmedValidator']
      ) {
        return;
      }
      if (control.value !== matchingControl.value) {
        matchingControl.setErrors({ confirmedValidator: true });
      } else {
        matchingControl.setErrors(null);
      }
    };
  }
}
