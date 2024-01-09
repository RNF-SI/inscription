import { Component } from '@angular/core';
import { UntypedFormGroup } from '@angular/forms';
import { IDropdownSettings } from 'ng-multiselect-dropdown';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { MultiSelectReservesOption } from 'src/app/models/models';
import { UserDataService } from 'src/app/services/user-data.service';

@Component({
  selector: 'app-moncompte',
  templateUrl: './moncompte.component.html',
  styleUrls: ['./moncompte.component.scss']
})
export class MoncompteComponent {

  form: UntypedFormGroup;
  user: any = [];
  selectText = 'Sélectionner des réserves'

  constructor(
    private authService: AuthService,
    // private roleFormService: RoleFormService,
     private userService: UserDataService
  ) {}

  reservesSelectSettings: IDropdownSettings;
  options: MultiSelectReservesOption[] = [];

  ngOnInit() {
    this.initForm();
    
    this.reservesSelectSettings = {
      singleSelection: false,
      idField: 'id',
      textField: 'name',
      allowSearchFilter: true,
      enableCheckAll: true,
      selectAllText:'Toutes les réserves',
      unSelectAllText: 'Aucune réserve',
      
      // placeholder: 'Sélectionner vos réserves',
      searchPlaceholderText: 'Rechercher'
    }
  }

  initForm() {
    this.options = [];
    this.form = this.getForm(this.authService.getCurrentUser().id_role);
    this.userService.getRole(this.authService.getCurrentUser().id_role).subscribe(
      obj => {
        obj.organisme.rns.forEach((rn: { rn: { area_code: any; area_name: any; }; }) => {
          this.options.push({
            id: rn.rn.area_code,
            name: rn.rn.area_name
          });  
        });
        this.user = obj;
      }
    );
  }

  getForm(role: number): UntypedFormGroup {
    return this.userService.getForm(role);
  }

  save() {
    if (this.form.valid) {
      this.userService.putRole(this.form.value).subscribe((res) => this.form.disable());
      this.userService.getRole(this.authService.getCurrentUser().id_role).subscribe(
        obj => {
          this.user = obj;
          console.log(this.user);
        }
      );
      
    }
  }

  cancel() {
    this.initForm();
    this.form.disable();
  }
}