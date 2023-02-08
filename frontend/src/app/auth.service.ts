import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { HttpClient } from '@angular/common/http';

@Injectable({
  providedIn: 'root'
})
export class AuthService {

  constructor(
    private _http: HttpClient,
  ) { }

  signupUser(data: any): Observable<any> {
    const options = data;
    console.log(options);
    
    return this._http.post<any>(`http://127.0.0.1:5070/inscription`, options);
  }
}
