import { HttpErrorResponse } from '@angular/common/http';
import { Component, Inject } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { Router } from '@angular/router';
import { AppConfig } from '../../../../conf/app.config';
import { AuthService } from '../../auth/auth-service.service';

export interface LoginData {
  code?: string;
  url?: string;
}

@Component({
  standalone: false,
  selector: 'pnx-login',
  templateUrl: 'login.component.html',
  styleUrls: ['./login.component.scss']
})
export class LoginComponent {
  enable_sign_up: boolean = false;
  enable_user_management: boolean = false;
  public disableSubmit = false;

  readonly form: UntypedFormGroup;
  returnUrl: string = '/';
  private identifiant: UntypedFormControl;
  private password: UntypedFormControl;

  public errorCode: string | null = null;
  public APP_NAME = AppConfig.appName;
  public showPassword = false;
  public progress = false;

  login_or_pass_recovery: boolean = false;

  constructor(
    @Inject(MAT_DIALOG_DATA) private data: LoginData,
    public _authService: AuthService,
    private ref: MatDialogRef<LoginComponent>,
    private router: Router
  ) {
    // Initialisation des contrôles de formulaire
    this.identifiant = new UntypedFormControl(null, Validators.required);
    this.password = new UntypedFormControl(null, Validators.required);
    this.form = new UntypedFormGroup({});
    this.form.addControl('identifiant', this.identifiant);
    this.form.addControl('password', this.password);

    // Récupère l'url de retour depuis les données du dialogue
    if (data && data.url) {
      this.returnUrl = data.url;
    }

    // IMPORTANT : Supprimez ou commentez l'abonnement beforeClosed() qui interfère avec afterClosed()
    // this.ref.beforeClosed().subscribe(user => (user && this.navigate(data.url)));
  }

  signIn() {
    this.progress = true;
    this._authService.signinUser(this.identifiant.value, this.password.value)
      .subscribe({
        next: (user) => {
          // Connexion réussie : fermer le dialogue en renvoyant l'utilisateur
          this.ref.close(user);
        },
        error: (error: HttpErrorResponse) => {
          this.showError(error);
        }
      });
  }

  clikonforgot() {
    // Redirige vers la réinitialisation du mot de passe, puis ferme le dialogue
    this.router.navigate(['/mot-de-passe-oublie']);
    this.ref.close(false);
  }

  /**
   * Affiche le message d'erreur
   * @param error : objet HttpErrorResponse contenant l'erreur
   */
  private showError(error: HttpErrorResponse) {
    this.progress = false;
    this.errorCode = error.error['type'];
    // Réinitialise le message d'erreur après 10 secondes
    setTimeout(() => this.errorCode = null, 10000);
  }
}
