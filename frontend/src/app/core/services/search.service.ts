import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface SearchItem {
  slug: string;
  nom: string;
}

@Injectable({
  providedIn: 'root'
})
export class SearchService {

  constructor(private http: HttpClient) { }

  getSearchItems(apiUrl: string): Observable<SearchItem[]> {
    return this.http.get<SearchItem[]>(`${environment.apiUrl}/${apiUrl}`);
  }
}
