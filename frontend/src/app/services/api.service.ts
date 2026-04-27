import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';

export interface ApplicationDto {
  slug: string;
  nom: string;
  url: string;
  image: string;
  description: string;
  managed_by_si: boolean;
  requires_access_request: boolean;
}

export interface MeApplicationRow {
  application: ApplicationDto;
  access_status: string;
}

export interface KeycloakPublicConfig {
  keycloakUrl: string;
  realm: string;
  clientId: string;
}

export interface MeResponse {
  profile: {
    keycloak_sub: string;
    email: string;
    username: string;
    first_name: string;
    last_name: string;
    is_super_admin: boolean;
    legacy_id_role: number | null;
  };
  applications: MeApplicationRow[];
  reserves: { area_code: string; area_name: string; referent: boolean; referent_valid: boolean }[];
  is_app_admin: boolean;
  unread_notifications: number;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  getKeycloakPublicConfig(): Observable<KeycloakPublicConfig> {
    return this.http.get<KeycloakPublicConfig>(`${environment.apiUrl}/auth/keycloak-config/`);
  }

  getApplications(): Observable<ApplicationDto[]> {
    return this.http.get<ApplicationDto[]>(`${environment.apiUrl}/applications/`);
  }

  getMe(): Observable<MeResponse> {
    return this.http.get<MeResponse>(`${environment.apiUrl}/me/`);
  }

  exchangeCode(code: string, redirectUri: string): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${environment.apiUrl}/auth/token/`, {
      code,
      redirect_uri: redirectUri,
    });
  }

  refreshToken(refreshToken: string): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(`${environment.apiUrl}/auth/refresh/`, {
      refresh_token: refreshToken,
    });
  }

  getAdminRegistrations(): Observable<{ public_id: string; status: string; email: string }[]> {
    return this.http.get<{ public_id: string; status: string; email: string }[]>(
      `${environment.apiUrl}/admin/registration-requests/`
    );
  }

  superApprove(publicId: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/admin/registration-requests/${publicId}/super-approve/`, {});
  }

  superReject(publicId: string, note?: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/admin/registration-requests/${publicId}/super-reject/`, { note });
  }

  getPendingItems(): Observable<
    {
      kind: string;
      item_id: number;
      application: ApplicationDto;
      registration_public_id?: string;
      request_public_id?: string;
      applicant_email: string;
      request_justification?: string;
    }[]
  > {
    return this.http.get<
      {
        kind: string;
        item_id: number;
        application: ApplicationDto;
        registration_public_id?: string;
        request_public_id?: string;
        applicant_email: string;
        request_justification?: string;
      }[]
    >(`${environment.apiUrl}/admin/pending-items/`);
  }

  decideRegistrationItem(itemId: number, approve: boolean, note?: string): Observable<unknown> {
    const d = approve ? 'approve' : 'reject';
    return this.http.post(`${environment.apiUrl}/admin/registration-items/${itemId}/${d}/`, { note });
  }

  decideAdditionalItem(itemId: number, approve: boolean, note?: string): Observable<unknown> {
    const d = approve ? 'approve' : 'reject';
    return this.http.post(`${environment.apiUrl}/admin/additional-items/${itemId}/${d}/`, { note });
  }

  requestAdditionalAccess(slugs: string[], remarks: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/me/additional-access/`, {
      application_slugs: slugs,
      remarks,
    });
  }

  getNotifications(): Observable<{ id: number; title: string; body: string; read: boolean; created_at: string }[]> {
    return this.http.get<
      { id: number; title: string; body: string; read: boolean; created_at: string }[]
    >(`${environment.apiUrl}/notifications/`);
  }

  markNotificationRead(id: number): Observable<unknown> {
    return this.http.patch(`${environment.apiUrl}/notifications/${id}/mark-read/`, {});
  }
}
