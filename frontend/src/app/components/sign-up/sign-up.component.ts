import { AfterViewInit, ChangeDetectorRef, Component, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { UntypedFormBuilder, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { MatSelect } from '@angular/material/select';
import { Router } from '@angular/router';

import { ToastrService } from 'ngx-toastr';
import { ReplaySubject, Subject, take, takeUntil } from 'rxjs';

import { IDropdownSettings } from 'ng-multiselect-dropdown';
import { RegisterService } from 'src/app/services/register.service';
import { MultiSelectReservesOption, Organisme, OrganismeComplet } from '../../models/models';

type SignupApplication = {
  slug: string;
  nom: string;
  managed_by_si: boolean;
  requires_access_request: boolean;
};

@Component({
  standalone: false,
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
  requestableApplications: SignupApplication[] = [];
  openApplications: SignupApplication[] = [];
  selectedApplications: { [slug: string]: boolean } = {};
  applicationJustifications: { [slug: string]: string } = {};

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
    private _toasterService: ToastrService,
    private cdr: ChangeDetectorRef,
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
        this.cdr.markForCheck();
      }
    );
    this._registerService.getApplications().subscribe((apps) => {
      const list: SignupApplication[] = apps || [];
      this.requestableApplications = list.filter((a) => a.requires_access_request);
      this.openApplications = list.filter((a) => a.managed_by_si && !a.requires_access_request);
      this.cdr.markForCheck();
    });
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
      identifiant: ['', [Validators.required, Validators.pattern(/^[A-Za-z0-9._-]+$/)]],
      email: [
        '',
        [Validators.email, Validators.required],
      ],
      password: ['', [Validators.required, Validators.minLength(8)]],
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

    this.appFormGroup = this.fb.group({
      reserves: ['', null],
      reserves_referent: ['', null],
    });
  }

  toggleApplication(slug: string, checked: boolean) {
    this.selectedApplications[slug] = checked;
    if (!checked) {
      this.applicationJustifications[slug] = '';
    }
  }

  setJustification(slug: string, value: string) {
    this.applicationJustifications[slug] = value;
  }

  isApplicationSelected(slug: string): boolean {
    return !!this.selectedApplications[slug];
  }

  selectedRequestableCount(): number {
    return Object.keys(this.selectedApplications).filter((s) => this.selectedApplications[s]).length;
  }

  invalidSelectedApplications(): SignupApplication[] {
    return this.requestableApplications.filter(
      (app) => this.selectedApplications[app.slug] && !(this.applicationJustifications[app.slug] || '').trim()
    );
  }

  buildApplicationsPayload() {
    return this.requestableApplications
      .filter((app) => this.selectedApplications[app.slug])
      .map((app) => ({
        application_slug: app.slug,
        justification: (this.applicationJustifications[app.slug] || '').trim(),
      }));
  }

  save() {
    if (this.form.valid) {
      const invalid = this.invalidSelectedApplications();
      if (invalid.length > 0) {
        this._toasterService.error(
          'Merci de renseigner une justification pour chaque application demandée.',
          'Inscription'
        );
        return;
      }
      this.disableSubmit = true;
      // mise en minuscule du mail (pour faciliter la vérification)
      this.form.value['email'] = this.form.value['email'].toLowerCase();
      const finalForm = Object.assign({}, this.form.value);
      // concatenate two forms
      finalForm['champs_addi'] = this.appFormGroup.value;
      finalForm['applications'] = this.buildApplicationsPayload();
      this._registerService
        .signupUser(finalForm)
        .subscribe((res) => {
          this._toasterService.info('Vous recevrez un mail de confirmation quand elle aura été validée par un administrateur.', 'Votre demande d\'inscription a bien été prise en compte !')
          this.router.navigate(['/']);
        },
          error => {
            const body = error.error;
            const detail =
              body?.msg ||
              (body?.errors ? JSON.stringify(body.errors) : '') ||
              error.message ||
              'Erreur serveur';
            this._toasterService.error(detail, 'Inscription');
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