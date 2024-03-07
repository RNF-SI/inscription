import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { environment } from 'src/environments/environment';

@Injectable({
  providedIn: 'root'
})
export class RegisterService {

  httpOptions = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' })
  };

  constructor(
    private _http: HttpClient,
  ) { }

  signupUser(data: any): Observable<any> {
    const options = data;
    
    return this._http.post<any>(`${environment.apiUrl}/inscription`, options);
  }

  getOrganismes() {
    return this._http.get<any>(
      `${environment.apiUrl}/organismes`,
      this.httpOptions
    );
  }

  getOrganisme(id : any) {
    return this._http.get<any>(
      `${environment.apiUrl}/organisme/`+id,
      this.httpOptions
    );
  }

  passwordChange(data : any) {
    return this._http.put<any>(`${environment.apiUrl}/password/new`, data);
  }
}
