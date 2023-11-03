import { Component } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastrService } from 'ngx-toastr';
import { RegisterService } from 'src/app/register.service';

@Component({
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
    private _registerService: RegisterService,
    private router: Router,
    private activatedRoute: ActivatedRoute,
    private _toasterService: ToastrService
  ) {
    this.activatedRoute.queryParams.subscribe((params) => {
      let token = params['token'];
      
      if (!RegExp('^[0-9]+$').test(token)) {
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
      data['token'] = this.token;
      this._registerService.passwordChange(data).subscribe(
        (res) => {
          this._toasterService.info(res.msg, '', {
            positionClass: 'toast-top-center',
            tapToDismiss: true,
            timeOut: 10000,
          });
          this.router.navigate(['/']);
        },
        // error callback
        (error) => {
          this._toasterService.error(error.error.msg, '');
        }
      );
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
