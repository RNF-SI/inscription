import { AfterViewInit, Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { UntypedFormBuilder, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { MatSelect } from '@angular/material/select';
import { Router } from '@angular/router';

import { ToastrService } from 'ngx-toastr';
import { ReplaySubject, Subject, take, takeUntil } from 'rxjs';

import { IDropdownSettings } from 'ng-multiselect-dropdown';
import { RegisterService } from 'src/app/services/register.service';
import { MultiSelectReservesOption, Organisme, OrganismeComplet } from '../../models/models';

@Component({
  selector: 'app-sign-up',
  templateUrl: './sign-up.component.html',
  styleUrls: ['./sign-up.component.scss']
})

export class SignUpComponent implements OnInit, AfterViewInit, OnDestroy {
  form: UntypedFormGroup;
  appFormGroup: UntypedFormGroup;
  public disableSubmit = false;
  public formControlBuilded = false;
  protected organismes: Organisme[];
  public organisme: OrganismeComplet;

  searchTxt: any;
  ogListe: boolean = true;

  options: MultiSelectReservesOption[] = [];

  public orgaCtrl: UntypedFormControl = new UntypedFormControl();
  public orgFilterCtrl: UntypedFormControl = new UntypedFormControl();
  public filteredOrgs: ReplaySubject<Organisme[]> = new ReplaySubject<Organisme[]>(1);

  @ViewChild('singleSelect') singleSelect: MatSelect;
  protected _onDestroy = new Subject<void>();
  private lastSearch: string = '';

  constructor(
    private fb: UntypedFormBuilder,
    private _registerService: RegisterService,
    private router: Router,
    private _toasterService: ToastrService
  ) {
  }

  reservesSelectSettings: IDropdownSettings;

  onSelect(item: any) {
    console.log(this.form.get('reserves')?.value)

  }

  selectText = 'Sélectionner des réserves'
  ngOnInit() {

    this.reservesSelectSettings = {
      singleSelection: false,
      idField: 'id',
      textField: 'name',
      allowSearchFilter: true,
      enableCheckAll: true,
      selectAllText: 'Toutes les réserves',
      unSelectAllText: 'Aucune réserve',

      // placeholder: 'Sélectionner vos réserves',
      searchPlaceholderText: 'Rechercher'
    }

    this.createForm();
    this._registerService.getOrganismes().subscribe(
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
      organisme: ['', Validators.required]
    },
      {
        validators: [
          this.ConfirmedValidator('password', 'password_confirmation'),
          this.atLeastOneRequired('id_organisme', 'organisme')
        ]

      }
    );

    this.form.get('id_organisme')?.valueChanges.subscribe(val => {
      this.options = [];

      this._registerService.getOrganisme(val).subscribe(
        res => {
          this.organisme = res
          this.organisme.rns.forEach(rn => {
            this.options.push({
              id: rn.rn.area_code,
              name: rn.rn.area_name
            });
          });
          this.options = [...this.options]

        }
      );
    })

    // this.form.setValidators([this.similarValidator('password', 'password_confirmation')]);
    this.appFormGroup = this.fb.group({
      reserves: ['', null],
      reserves_referent: ['', null],
      geonature_saisie: [false, null],
      precisions_geonature_saisie: ['', null],
      psdrf: [false, null],
      precisions_psdrf: ['', null],
      ancrage: [false, null],
      precisions_ancrage: ['', null],
      opnl: [false, null],
      precisions_opnl: ['', null],
      waterwise: [false, null],
      precisions_waterwise: ['', null]
    });

    this.appFormGroup.get('geonature_saisie')?.valueChanges.subscribe(val => {
      if (val == true) {
        this.appFormGroup.controls['precisions_geonature_saisie'].setValidators([Validators.required]);
      } else {
        this.appFormGroup.controls['precisions_geonature_saisie'].clearValidators();
      }
      this.appFormGroup.controls['precisions_geonature_saisie'].updateValueAndValidity();
    });

    this.appFormGroup.get('ancrage')?.valueChanges.subscribe(val => {
      if (val == true) {
        this.appFormGroup.controls['precisions_ancrage'].setValidators([Validators.required]);
      } else {
        this.appFormGroup.controls['precisions_ancrage'].clearValidators();
      }
      this.appFormGroup.controls['precisions_ancrage'].updateValueAndValidity();
    });

    this.appFormGroup.get('psdrf')?.valueChanges.subscribe(val => {
      if (val == true) {
        this.appFormGroup.controls['precisions_psdrf'].setValidators([Validators.required]);
      } else {
        this.appFormGroup.controls['precisions_psdrf'].clearValidators();
      }
      this.appFormGroup.controls['precisions_psdrf'].updateValueAndValidity();
    });

    this.appFormGroup.get('opnl')?.valueChanges.subscribe(val => {
      if (val == true) {
        this.appFormGroup.controls['precisions_opnl'].setValidators([Validators.required]);
      } else {
        this.appFormGroup.controls['precisions_opnl'].clearValidators();
      }
      this.appFormGroup.controls['precisions_opnl'].updateValueAndValidity();
    })
    this.appFormGroup.get('waterwise')?.valueChanges.subscribe(val => {
      if (val == true) {
        this.appFormGroup.controls['precisions_waterwise'].setValidators([Validators.required]);
      } else {
        this.appFormGroup.controls['precisions_waterwise'].clearValidators();
      }
      this.appFormGroup.controls['precisions_waterwise'].updateValueAndValidity();
    })
  }

  save() {
    if (this.form.valid) {
      this.disableSubmit = true;
      // mise en minuscule du mail (pour faciliter la vérification)
      this.form.value['email'] = this.form.value['email'].toLowerCase();
      const finalForm = Object.assign({}, this.form.value);
      // concatenate two forms
      finalForm['champs_addi'] = this.appFormGroup.value;
      this._registerService
        .signupUser(finalForm)
        .subscribe((res) => {
          this._toasterService.info('Vous recevrez un mail de confirmation quand elle aura été validée par un administrateur.', 'Votre demande d\'inscription a bien été prise en compte !')
          this.router.navigate(['/']);
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

  atLeastOneRequired(valueName1: string, valueName2: string) {
    return (formgroup: UntypedFormGroup) => {
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
    if (this.orgFilterCtrl && this.orgFilterCtrl.value != value) this.orgFilterCtrl.setValue(value, { emitEvent: false });
  }

}