import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { HttpClient, HttpHeaders } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class AuthService {

  httpOptions = {
    headers: new HttpHeaders({ 'Content-Type': 'application/json' })
  };

  constructor(
    private _http: HttpClient,
  ) { }

  signupUser(data: any): Observable<any> {
    const options = data;
    console.log(options);
    
    return this._http.post<any>(`http://127.0.0.1:5070/inscription`, options);
  }

  getOrganismes() {
    return this._http.get<any>(
      `http://127.0.0.1:5070/organismes`,
      this.httpOptions
    );
  }
}
