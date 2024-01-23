import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { map, Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

@Injectable({
  providedIn: 'root'
})
export class UserDataService {

  private roleForm: UntypedFormGroup;
  

  constructor(
    private fb: UntypedFormBuilder,
    private _http: HttpClient
    ) {
    this.setForm();
  }

  getForm(id: number): UntypedFormGroup {
    if (id !== null) {
      this.getRole(id);
    }
    return this.roleForm;
  }

  private setForm() {
    this.roleForm = this.fb.group({
      identifiant: ['', Validators.required],
      nom_role: ['', Validators.required],
      prenom_role: ['', Validators.required],
      organisme: ['', null],
      email: [
        '',
        [Validators.pattern('^[a-z0-9._-]+@[a-z0-9._-]{2,}.[a-z]{2,4}$'), Validators.required],
      ],
      remarques: ['', null],
      reserves: ['', null],
      reserves_referent: ['', null]
    });
    this.roleForm.disable();
  }

  getRole(id: number) {
    this._http.get<any>(`${environment.apiUrl}/user/${id}`).subscribe((res) => {
      this.roleForm.patchValue(res);
      this.roleForm.get('organisme')?.patchValue(res.organisme.nom_organisme);
      let rns: { id: any; name: any; }[] = []
      let referents: { id: any; name: any; }[] = []
      res.rns.forEach((rn: {
        referent: boolean;referent_valid: boolean, rn: { area_code: any; area_name: any; }; 
}) => {
        rns.push({
          id: rn.rn.area_code,
          name: rn.rn.area_name
        }); 
        if (rn.referent ) {
          referents.push({
            id: rn.rn.area_code,
            name: rn.rn.area_name
          }); 
        }  
      });
      this.roleForm.get('reserves')?.patchValue(rns)
      this.roleForm.get('reserves_referent')?.patchValue(referents)

    });
    return this._http.get<any>(`${environment.apiUrl}/user/${id}`)
  }

  putRole(role: any) {
    const options = role;
    return this._http.put<any>(`${environment.apiUrl}/role`, options).pipe(
      map((res: any) => {
        return res;
      })
    );
  }
}
