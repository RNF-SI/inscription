import { Component, OnInit } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ValidatorFn, AbstractControl } from '@angular/forms';
import { Router } from '@angular/router';

import { ToastrService } from 'ngx-toastr';
import { AuthService } from '../auth.service';

@Component({
  selector: 'app-sign-up',
  templateUrl: './sign-up.component.html',
  styleUrls: ['./sign-up.component.scss']
})

export class SignUpComponent implements OnInit {
  form: FormGroup;
  appFormGroup: FormGroup;
  public disableSubmit = false;
  public formControlBuilded = false;

  constructor(
    private fb: FormBuilder,
    private _authService: AuthService,
    private router: Router,
    private _toasterService: ToastrService
  ) {
  }

  ngOnInit() {
    this.createForm();
  }

  createForm() {
    this.form = this.fb.group({
      nom_role: ['', Validators.required],
      prenom_role: ['', Validators.required],
      identifiant: ['', Validators.required],
      email: [
        '',
        [Validators.email, Validators.required],
      ],
      password: ['', [Validators.required]],
      password_confirmation: ['', [Validators.required]],
      remarques: ['', Validators.required],
      organisme: ['', Validators.required],
    },
    {
      validator: this.ConfirmedValidator('password','password_confirmation')
    });
    // this.form.setValidators([this.similarValidator('password', 'password_confirmation')]);
    this.appFormGroup = this.fb.group({
      geonature_saisie: [false, null],
      psdrf: [false, null],
      ancrage: [false, null],
      opnl: [false, null],
      precisions: ['', null]
    });
  }

  save() {
    if (this.form.valid) {
      this.disableSubmit = true;
      const finalForm = Object.assign({}, this.form.value);
      // concatenate two forms
      finalForm['champs_addi'] = this.appFormGroup.value;
      this._authService
        .signupUser(finalForm)
        .subscribe((res) => {
          
          // const callbackMessage = AppConfig.ACCOUNT_MANAGEMENT.AUTO_ACCOUNT_CREATION
          //   ? 'AutoAccountEmailConfirmation'
          //   : 'AdminAccountEmailConfirmation';
          // this._commonService.translateToaster('info', callbackMessage);
          this._toasterService.info('Votre demande d\'inscription a bien été prise en compte !','')
          this.form.reset();
          this.appFormGroup.reset();
          window.scroll({ 
            top: 0, 
            left: 0, 
            behavior: 'smooth' 
     });
        },
        error => {
          this._toasterService.error(error.error.msg, '');
        })
        .add(() => {
          this.disableSubmit = false;
        });
    }
  }

  ConfirmedValidator(controlName: string, matchingControlName: string) {
    return (formGroup: FormGroup) => {
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

  // similarValidator(pass: string, passConfirm: string): ValidatorFn {
  //   return (control: FormGroup): { [key: string]: any } => {
  //     const passControl = control.get(pass);
  //     const confirPassControl = control.get(passConfirm);
  //     if (passControl && confirPassControl && passControl.value === confirPassControl.value) {
  //       return null;
  //     }
  //     return { similarError: true };
  //   };
  // }
}