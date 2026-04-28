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
    fonction?: string;
    organisme?: string;
    is_super_admin: boolean;
    legacy_id_role: number | null;
  };
  applications: MeApplicationRow[];
  reserves: { area_code: string; area_name: string; referent: boolean; referent_valid: boolean; referent_pending?: boolean }[];
  is_app_admin: boolean;
  unread_notifications: number;
}

export interface ReserveOptionDto {
  area_code: string;
  area_name: string;
  principal?: boolean;
}

export interface ReferentReserveMemberDto {
  sub: string;
  email: string;
  first_name: string;
  last_name: string;
  username: string;
  pending_removal_request?: boolean;
}

export interface ReferentReserveMembersRowDto {
  reserve: { area_code: string; area_name: string };
  can_request_removal?: boolean;
  can_direct_remove?: boolean;
  can_direct_add?: boolean;
  members: ReferentReserveMemberDto[];
}

export interface AdminReserveMemberRemovalRequestDto {
  id: number;
  reserve: { area_code: string; area_name: string };
  requester_email: string;
  requester_name: string;
  target_sub: string;
  target_email: string;
  target_first_name: string;
  target_last_name: string;
  reason: string;
  created_at: string;
}

export interface AdminReserveReferentRequestDto {
  id: number;
  reserve: { area_code: string; area_name: string };
  user_sub: string;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  user_fonction?: string;
}

export interface ApplicationAdminUserDto {
  keycloak_sub: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface ApplicationAdminsRowDto {
  application: ApplicationDto;
  admins: ApplicationAdminUserDto[];
}

export interface KeycloakUserSuggestionDto {
  keycloak_sub: string;
  email: string;
  first_name: string;
  last_name: string;
  username: string;
  label: string;
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

  updateMe(payload: {
    username?: string;
    email?: string;
    first_name?: string;
    last_name?: string;
    fonction?: string;
  }): Observable<MeResponse> {
    return this.http.patch<MeResponse>(`${environment.apiUrl}/me/`, payload);
  }

  getMyReserveOptions(): Observable<ReserveOptionDto[]> {
    return this.http.get<ReserveOptionDto[]>(`${environment.apiUrl}/me/reserve-options/`);
  }

  addMyReserve(areaCode: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/me/reserves/${areaCode}/`, {});
  }

  removeMyReserve(areaCode: string): Observable<unknown> {
    return this.http.delete(`${environment.apiUrl}/me/reserves/${areaCode}/`);
  }

  requestMyReserveReferent(areaCode: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/me/reserves/${areaCode}/referent-request/`, {});
  }

  getReferentReserveMembers(): Observable<ReferentReserveMembersRowDto[]> {
    return this.http.get<ReferentReserveMembersRowDto[]>(`${environment.apiUrl}/me/referent/reserves-members/`);
  }

  requestReserveMemberRemoval(
    areaCode: string,
    payload: { target_sub: string; target_email?: string; target_first_name?: string; target_last_name?: string; reason: string }
  ): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/me/referent/reserves/${areaCode}/removal-requests/`, payload);
  }

  directRemoveReserveMember(areaCode: string, userSub: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/admin/reserves/${areaCode}/members/${userSub}/remove/`, {});
  }

  directAddReserveMember(areaCode: string, email: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/admin/reserves/${areaCode}/members/add/`, { email });
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

  getAdminRegistrations(): Observable<
    {
      public_id: string;
      status: string;
      email: string;
      first_name: string;
      last_name: string;
      fonction: string;
      organisme: string;
    }[]
  > {
    return this.http.get<
      {
        public_id: string;
        status: string;
        email: string;
        first_name: string;
        last_name: string;
        fonction: string;
        organisme: string;
      }[]
    >(
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
      applicant_first_name?: string;
      applicant_last_name?: string;
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
        applicant_first_name?: string;
        applicant_last_name?: string;
        request_justification?: string;
      }[]
    >(`${environment.apiUrl}/admin/pending-items/`);
  }

  getMyValidationApplications(): Observable<ApplicationDto[]> {
    return this.http.get<ApplicationDto[]>(`${environment.apiUrl}/admin/my-validation-applications/`);
  }

  searchKeycloakUsers(query: string): Observable<KeycloakUserSuggestionDto[]> {
    return this.http.get<KeycloakUserSuggestionDto[]>(
      `${environment.apiUrl}/admin/keycloak-users-search/?q=${encodeURIComponent(query)}`
    );
  }

  getApplicationAdmins(): Observable<ApplicationAdminsRowDto[]> {
    return this.http.get<ApplicationAdminsRowDto[]>(`${environment.apiUrl}/admin/application-admins/`);
  }

  assignApplicationAdmin(applicationSlug: string, email: string): Observable<unknown> {
    return this.http.post(`${environment.apiUrl}/admin/applications/${applicationSlug}/admins/`, { email });
  }

  removeApplicationAdmin(applicationSlug: string, userSub: string): Observable<unknown> {
    return this.http.delete(`${environment.apiUrl}/admin/applications/${applicationSlug}/admins/${userSub}/`);
  }

  getAdminReserveMemberRemovalRequests(): Observable<AdminReserveMemberRemovalRequestDto[]> {
    return this.http.get<AdminReserveMemberRemovalRequestDto[]>(`${environment.apiUrl}/admin/reserve-member-removal-requests/`);
  }

  decideAdminReserveMemberRemovalRequest(reqId: number, approve: boolean, note?: string): Observable<unknown> {
    const d = approve ? 'approve' : 'reject';
    return this.http.post(`${environment.apiUrl}/admin/reserve-member-removal-requests/${reqId}/${d}/`, { note });
  }

  getAdminReserveReferentRequests(): Observable<AdminReserveReferentRequestDto[]> {
    return this.http.get<AdminReserveReferentRequestDto[]>(`${environment.apiUrl}/admin/reserve-referent-requests/`);
  }

  decideAdminReserveReferentRequest(reqId: number, approve: boolean, note?: string): Observable<unknown> {
    const d = approve ? 'approve' : 'reject';
    return this.http.post(`${environment.apiUrl}/admin/reserve-referent-requests/${reqId}/${d}/`, { note });
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
