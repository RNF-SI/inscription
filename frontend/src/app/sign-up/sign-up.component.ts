import { AfterViewInit, Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormGroup, FormBuilder, Validators, ValidatorFn, AbstractControl, FormControl } from '@angular/forms';
import { MatSelect } from '@angular/material/select';
import { Router } from '@angular/router';

import { ToastrService } from 'ngx-toastr';
import { ReplaySubject, Subject, take, takeUntil } from 'rxjs';
import { AuthService } from '../auth.service';

import { Organisme } from '../models/models';

import { Bank, BANKS } from '../demo-data';

@Component({
  selector: 'app-sign-up',
  templateUrl: './sign-up.component.html',
  styleUrls: ['./sign-up.component.scss']
})

export class SignUpComponent implements OnInit, AfterViewInit, OnDestroy {
  form: FormGroup;
  appFormGroup: FormGroup;
  public disableSubmit = false;
  public formControlBuilded = false;
  protected organismes: Organisme[];
  searchTxt: any;
  ogListe : boolean = true;

  public orgaCtrl: FormControl = new FormControl();
  public orgFilterCtrl: FormControl = new FormControl();
  public filteredOrgs: ReplaySubject<Organisme[]> = new ReplaySubject<Organisme[]>(1);

  @ViewChild('singleSelect') singleSelect: MatSelect;
  protected _onDestroy = new Subject<void>();
  private lastSearch: string ='';

  constructor(
    private fb: FormBuilder,
    private _authService: AuthService,
    private router: Router,
    private _toasterService: ToastrService
  ) {
  }

  ngOnInit() {
    this.createForm();
    this._authService.getOrganismes().subscribe(
      res => {
        this.organismes = res
        this.filteredOrgs.next(this.organismes.slice());
        this.orgFilterCtrl.valueChanges
          .pipe(takeUntil(this._onDestroy))
          .subscribe(() => {
            this.filterOrgs();
          });
      }
    );   
  }

  ngAfterViewInit() {
    this.setInitialValue();
  }

  ngOnDestroy() {
    this._onDestroy.next();
    this._onDestroy.complete();
  }

  protected setInitialValue() {
    this.filteredOrgs
      .pipe(take(1), takeUntil(this._onDestroy))
      .subscribe(() => {
        // setting the compareWith property to a comparison function
        // triggers initializing the selection according to the initial value of
        // the form control (i.e. _initializeSelection())
        // this needs to be done after the filteredBanks are loaded initially
        // and after the mat-option elements are available
        this.singleSelect.compareWith = (a: Organisme, b: Organisme) => a && b && a.id_organisme === b.id_organisme;
      });  
  }

  protected filterOrgs() {
    if (!this.organismes) {
      return;
    }
    let search: string;

    search = this.orgFilterCtrl.value;
    if (!search) {
      this.writeValue(this.lastSearch);
      this.filteredOrgs.next(
        this.organismes.filter(organisme => organisme.nom_organisme.toLowerCase().indexOf(this.lastSearch) > -1)
      ); 
      this.lastSearch = '';
      return;
    } else {
      search = search.toLowerCase();
    }
    this.filteredOrgs.next(
      this.organismes.filter(organisme => organisme.nom_organisme.toLowerCase().indexOf(search) > -1)
    );  
    this.lastSearch = search;
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
      id_organisme: ['', Validators.required],
      organisme: ['', Validators.required],
    },
    {
      validators: [
        this.ConfirmedValidator('password','password_confirmation'),
        this.atLeastOneRequired('id_organisme', 'organisme')
      ]

    }
    );
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
          this._toasterService.info('Vous recevrez un mail de confirmation quand elle aura été validée par un administrateur.','Votre demande d\'inscription a bien été prise en compte !')
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

  atLeastOneRequired(valueName1: string, valueName2: string) {
    return (formgroup: FormGroup) => {
      const value1 = formgroup.controls[valueName1];
      const value2 = formgroup.controls[valueName2];
      if (value1.value || value2.value) {
        value1.setErrors(null);
        value2.setErrors(null);
      } else {
        value1.setErrors({ atLeastOneRequired: true });
        value2.setErrors({ atLeastOneRequired: true });
      }
    }
  }

  nouvelOg() {
    this.ogListe = false;
    this.form.get('id_organisme')!.patchValue('');
  }

  writeValue(value: any): void {
    if(this.orgFilterCtrl && this.orgFilterCtrl.value!=value) this.orgFilterCtrl.setValue(value, { emitEvent: false });
  }

}