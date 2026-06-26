import { Component, OnInit } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';
import {
  AdminReserveReferentRequestDto,
  AdminReserveMemberRemovalRequestDto,
  ApiService,
  ApplicationDto,
  ApplicationAdminsRowDto,
  KeycloakUserSuggestionDto,
  UserApplicationAccessDto,
  UserApplicationAccessRowDto,
  ReferentReserveMembersRowDto,
} from 'src/app/services/api.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';

@Component({
  selector: 'app-admin-dashboard',
  templateUrl: './admin-dashboard.component.html',
})
export class AdminDashboardComponent implements OnInit {
  activeTab: 'requests' | 'reserves' | 'app-admins' | 'user-access' = 'requests';
  tabLoading: Record<'requests' | 'reserves' | 'app-admins' | 'user-access', boolean> = {
    requests: false,
    reserves: false,
    'app-admins': false,
    'user-access': false,
  };
  tabLoaded: Record<'requests' | 'reserves' | 'app-admins' | 'user-access', boolean> = {
    requests: false,
    reserves: false,
    'app-admins': false,
    'user-access': false,
  };
  isSuperAdmin = false;
  registrations: {
    public_id: string;
    status: string;
    email: string;
    first_name: string;
    last_name: string;
    fonction: string;
    organisme: string;
  }[] = [];
  pending: {
    kind: string;
    item_id: number;
    applicant_email: string;
    applicant_first_name?: string;
    applicant_last_name?: string;
    application: { nom: string; slug: string };
    request_justification?: string;
  }[] = [];
  validationApplications: ApplicationDto[] = [];
  decisionLoadingKey: string | null = null;
  appAdminRows: ApplicationAdminsRowDto[] = [];
  appAdminAvailable = true;
  appAdminEmailBySlug: Record<string, string> = {};
  appAdminActionKey: string | null = null;
  rejectionModalOpen = false;
  rejectionReason = '';
  rejectionTarget: { itemId: number; kind: string } | null = null;
  reserveRemovalRequests: AdminReserveMemberRemovalRequestDto[] = [];
  reserveRemovalNoteById: Record<number, string> = {};
  reserveRemovalLoadingKey: string | null = null;
  reserveReferentRequests: AdminReserveReferentRequestDto[] = [];
  reserveReferentNoteById: Record<number, string> = {};
  reserveReferentLoadingKey: string | null = null;
  referentReserves: ReferentReserveMembersRowDto[] = [];
  selectedReferentReserveCode = '';
  referentRemovalModalOpen = false;
  referentRemovalReason = '';
  referentRemovalTarget:
    | {
        areaCode: string;
        reserveName: string;
        member: { sub: string; email: string; first_name: string; last_name: string };
      }
    | null = null;
  referentRemovalSavingKey: string | null = null;
  reserveMemberAddEmailByCode: Record<string, string> = {};
  reserveMemberAddLoadingCode: string | null = null;
  reserveMemberSearchLoadingCode: string | null = null;
  reserveMemberAddSuggestionsByCode: Record<string, KeycloakUserSuggestionDto[]> = {};
  isReserveReferent = false;
  userAccessSearchQuery = '';
  userAccessSuggestions: KeycloakUserSuggestionDto[] = [];
  userAccessSearchLoading = false;
  selectedUserAccessSub = '';
  selectedUserAccessLabel = '';
  userAccessData: UserApplicationAccessDto | null = null;
  userAccessDraft: Record<string, boolean> = {};
  userAccessSaving = false;
  userAccessLoadError = '';

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnInit(): void {
    const me = this.auth.getMeSnapshot();
    this.isSuperAdmin = !!me?.profile?.is_super_admin;
    this.isReserveReferent = !!me?.reserves?.some((r) => !!r.referent);
    if (!this.canShowRequestsTab && this.canShowReservesTab) {
      this.activeTab = 'reserves';
    } else if (!this.canShowRequestsTab && this.activeTab === 'requests') {
      this.activeTab = this.canShowAppAdminsTab ? 'app-admins' : 'requests';
    }
    if (!this.canShowReservesTab && this.activeTab === 'reserves') {
      this.activeTab = this.canShowRequestsTab ? 'requests' : 'app-admins';
    }
    if (!this.canShowAppAdminsTab && this.activeTab === 'app-admins') {
      this.activeTab = this.canShowRequestsTab ? 'requests' : 'reserves';
    }
    this.loadTab(this.activeTab);
  }

  get canValidateApplications(): boolean {
    return this.validationApplications.length > 0;
  }

  get validationApplicationsLabel(): string {
    return this.validationApplications.map((a) => a.nom).join(', ');
  }

  get useReferentReserveSelector(): boolean {
    return this.referentReserves.length > 3;
  }

  get displayedReferentReserves(): ReferentReserveMembersRowDto[] {
    if (!this.useReferentReserveSelector) {
      return this.referentReserves;
    }
    const selected = this.referentReserves.find((r) => r.reserve.area_code === this.selectedReferentReserveCode);
    return selected ? [selected] : [];
  }

  get currentUserSub(): string {
    return this.auth.getMeSnapshot()?.profile?.keycloak_sub || '';
  }

  canRequestRemovalForMember(memberSub: string): boolean {
    return !!memberSub && memberSub !== this.currentUserSub;
  }

  approveReg(id: string) {
    this.api.superApprove(id).subscribe(() => this.loadRequestsTab(true));
  }

  rejectReg(id: string) {
    this.api.superReject(id).subscribe(() => this.loadRequestsTab(true));
  }

  decide(itemId: number, kind: string, approve: boolean) {
    if (!approve) {
      this.openRejectionModal(itemId, kind);
      return;
    }
    this.submitDecision(itemId, kind, true, '');
  }

  openRejectionModal(itemId: number, kind: string): void {
    this.rejectionTarget = { itemId, kind };
    this.rejectionReason = '';
    this.rejectionModalOpen = true;
  }

  cancelRejectionModal(): void {
    this.rejectionModalOpen = false;
    this.rejectionReason = '';
    this.rejectionTarget = null;
  }

  confirmRejectionModal(): void {
    const reason = this.rejectionReason.trim();
    if (!this.rejectionTarget || !reason) {
      return;
    }
    const { itemId, kind } = this.rejectionTarget;
    this.cancelRejectionModal();
    this.submitDecision(itemId, kind, false, reason);
  }

  private submitDecision(itemId: number, kind: string, approve: boolean, note: string): void {
    const key = `${kind}:${itemId}:${approve ? 'approve' : 'reject'}`;
    this.decisionLoadingKey = key;
    const obs =
      kind === 'additional'
        ? this.api.decideAdditionalItem(itemId, approve, note)
        : this.api.decideRegistrationItem(itemId, approve, note);
    obs.subscribe({
      next: () => this.loadRequestsTab(true),
      error: () => {
        this.decisionLoadingKey = null;
      },
    });
  }

  isDecisionLoading(itemId: number, kind: string, approve: boolean): boolean {
    const key = `${kind}:${itemId}:${approve ? 'approve' : 'reject'}`;
    return this.decisionLoadingKey === key;
  }

  isAnyDecisionLoadingForRow(itemId: number, kind: string): boolean {
    return this.decisionLoadingKey?.startsWith(`${kind}:${itemId}:`) ?? false;
  }

  formatApplicantLabel(p: { applicant_first_name?: string; applicant_last_name?: string; applicant_email: string }): string {
    const fullName = `${p.applicant_first_name || ''} ${p.applicant_last_name || ''}`.trim();
    if (!fullName) {
      return p.applicant_email;
    }
    return `${fullName} (${p.applicant_email})`;
  }

  get pendingRegistrations() {
    return this.registrations.filter((r) => r.status === 'pending_super');
  }

  assignAppAdmin(applicationSlug: string): void {
    const email = (this.appAdminEmailBySlug[applicationSlug] || '').trim();
    if (!email) {
      return;
    }
    const key = `assign:${applicationSlug}`;
    this.appAdminActionKey = key;
    this.api.assignApplicationAdmin(applicationSlug, email).subscribe({
      next: () => {
        this.appAdminEmailBySlug[applicationSlug] = '';
        this.reloadAppAdmins();
      },
      error: () => {
        this.appAdminActionKey = null;
      },
    });
  }

  removeAppAdmin(applicationSlug: string, userSub: string): void {
    const key = `remove:${applicationSlug}:${userSub}`;
    this.appAdminActionKey = key;
    this.api.removeApplicationAdmin(applicationSlug, userSub).subscribe({
      next: () => this.reloadAppAdmins(),
      error: () => {
        this.appAdminActionKey = null;
      },
    });
  }

  isAppAdminActionLoading(key: string): boolean {
    return this.appAdminActionKey === key;
  }

  decideReserveRemoval(reqId: number, approve: boolean): void {
    const key = `${reqId}:${approve ? 'approve' : 'reject'}`;
    const note = approve ? '' : (this.reserveRemovalNoteById[reqId] || '').trim();
    if (!approve && !note) {
      return;
    }
    this.reserveRemovalLoadingKey = key;
    this.api.decideAdminReserveMemberRemovalRequest(reqId, approve, note).subscribe({
      next: () => this.loadRequestsTab(true),
      error: () => {
        this.reserveRemovalLoadingKey = null;
      },
    });
  }

  isReserveRemovalLoading(reqId: number, approve: boolean): boolean {
    return this.reserveRemovalLoadingKey === `${reqId}:${approve ? 'approve' : 'reject'}`;
  }

  openReferentRemovalModal(
    areaCode: string,
    reserveName: string,
    member: { sub: string; email: string; first_name: string; last_name: string }
  ): void {
    this.referentRemovalTarget = { areaCode, reserveName, member };
    this.referentRemovalReason = '';
    this.referentRemovalModalOpen = true;
  }

  cancelReferentRemovalModal(): void {
    this.referentRemovalModalOpen = false;
    this.referentRemovalReason = '';
    this.referentRemovalTarget = null;
  }

  confirmReferentRemovalModal(): void {
    if (!this.referentRemovalTarget) {
      return;
    }
    const reason = (this.referentRemovalReason || '').trim();
    if (!reason) {
      return;
    }
    const { areaCode, member } = this.referentRemovalTarget;
    this.cancelReferentRemovalModal();
    this.requestReferentRemoval(areaCode, member, reason);
  }

  requestReferentRemoval(
    areaCode: string,
    member: { sub: string; email: string; first_name: string; last_name: string },
    reason: string
  ): void {
    const key = `${areaCode}:${member.sub}`;
    if (!reason || this.referentRemovalSavingKey) {
      return;
    }
    this.referentRemovalSavingKey = key;
    this.api.requestReserveMemberRemoval(areaCode, {
      target_sub: member.sub,
      target_email: member.email,
      target_first_name: member.first_name,
      target_last_name: member.last_name,
      reason,
    }).subscribe({
      next: () => {
        this.loadReservesTab(true);
      },
      error: () => {
        this.referentRemovalSavingKey = null;
      },
      complete: () => {
        this.referentRemovalSavingKey = null;
      },
    });
  }

  directRemoveReserveMember(areaCode: string, member: { sub: string }): void {
    const key = `${areaCode}:${member.sub}`;
    if (this.referentRemovalSavingKey) {
      return;
    }
    this.referentRemovalSavingKey = key;
    this.api.directRemoveReserveMember(areaCode, member.sub).subscribe({
      next: () => this.loadReservesTab(true),
      error: () => {
        this.referentRemovalSavingKey = null;
      },
      complete: () => {
        this.referentRemovalSavingKey = null;
      },
    });
  }

  directAddReserveMember(areaCode: string): void {
    const email = (this.reserveMemberAddEmailByCode[areaCode] || '').trim();
    if (!email || this.reserveMemberAddLoadingCode) {
      return;
    }
    this.reserveMemberAddLoadingCode = areaCode;
    this.api.directAddReserveMember(areaCode, email).subscribe({
      next: () => {
        this.reserveMemberAddEmailByCode[areaCode] = '';
        this.loadReservesTab(true);
      },
      error: () => {
        this.reserveMemberAddLoadingCode = null;
      },
      complete: () => {
        this.reserveMemberAddLoadingCode = null;
      },
    });
  }

  isDirectAddLoading(areaCode: string): boolean {
    return this.reserveMemberAddLoadingCode === areaCode;
  }

  onReserveMemberAddInput(areaCode: string): void {
    const query = (this.reserveMemberAddEmailByCode[areaCode] || '').trim();
    if (query.length < 2) {
      this.reserveMemberAddSuggestionsByCode[areaCode] = [];
      return;
    }
    this.reserveMemberSearchLoadingCode = areaCode;
    this.api.searchKeycloakUsers(query).subscribe({
      next: (rows) => {
        this.reserveMemberAddSuggestionsByCode[areaCode] = rows || [];
      },
      error: () => {
        this.reserveMemberAddSuggestionsByCode[areaCode] = [];
      },
      complete: () => {
        this.reserveMemberSearchLoadingCode = null;
      },
    });
  }

  isReserveMemberSearchLoading(areaCode: string): boolean {
    return this.reserveMemberSearchLoadingCode === areaCode;
  }

  isReferentRemovalSaving(areaCode: string, sub: string): boolean {
    return this.referentRemovalSavingKey === `${areaCode}:${sub}`;
  }

  decideReserveReferent(reqId: number, approve: boolean): void {
    const key = `${reqId}:${approve ? 'approve' : 'reject'}`;
    const note = approve ? '' : (this.reserveReferentNoteById[reqId] || '').trim();
    if (!approve && !note) {
      return;
    }
    this.reserveReferentLoadingKey = key;
    this.api.decideAdminReserveReferentRequest(reqId, approve, note).subscribe({
      next: () => this.loadRequestsTab(true),
      error: () => {
        this.reserveReferentLoadingKey = null;
      },
    });
  }

  isReserveReferentLoading(reqId: number, approve: boolean): boolean {
    return this.reserveReferentLoadingKey === `${reqId}:${approve ? 'approve' : 'reject'}`;
  }

  setActiveTab(tab: 'requests' | 'reserves' | 'app-admins' | 'user-access'): void {
    if (tab === 'requests' && !this.canShowRequestsTab) {
      return;
    }
    if (tab === 'reserves' && !this.canShowReservesTab) {
      return;
    }
    if (tab === 'app-admins' && !this.canShowAppAdminsTab) {
      return;
    }
    if (tab === 'user-access' && !this.canShowUserAccessTab) {
      return;
    }
    this.activeTab = tab;
    this.loadTab(tab);
  }

  get canShowReservesTab(): boolean {
    return this.isSuperAdmin || this.isReserveReferent;
  }

  get canShowAppAdminsTab(): boolean {
    return this.isSuperAdmin;
  }

  get canShowUserAccessTab(): boolean {
    return this.isSuperAdmin;
  }

  get canShowRequestsTab(): boolean {
    return this.isSuperAdmin || this.canValidateApplications;
  }

  get visibleTabsCount(): number {
    return [this.canShowRequestsTab, this.canShowReservesTab, this.canShowAppAdminsTab, this.canShowUserAccessTab].filter(Boolean).length;
  }

  isTabLoading(tab: 'requests' | 'reserves' | 'app-admins' | 'user-access'): boolean {
    return this.tabLoading[tab];
  }

  private loadTab(tab: 'requests' | 'reserves' | 'app-admins' | 'user-access', force = false): void {
    if (this.tabLoading[tab] || (!force && this.tabLoaded[tab])) {
      return;
    }
    if (tab === 'requests') {
      this.loadRequestsTab(force);
      return;
    }
    if (tab === 'reserves') {
      this.loadReservesTab(force);
      return;
    }
    if (tab === 'user-access') {
      this.loadUserAccessTab(force);
      return;
    }
    this.loadAppAdminsTab(force);
  }

  private loadRequestsTab(force = false): void {
    if (this.tabLoading.requests || (!force && this.tabLoaded.requests)) {
      return;
    }
    this.tabLoading.requests = true;
    forkJoin({
      regs: this.api.getAdminRegistrations().pipe(catchError(() => of([]))),
      pend: this.api.getPendingItems().pipe(catchError(() => of([]))),
      validationApps: this.api.getMyValidationApplications().pipe(catchError(() => of([]))),
      reserveRemoval: this.api.getAdminReserveMemberRemovalRequests().pipe(catchError(() => of([]))),
      reserveReferentRequests: this.api.getAdminReserveReferentRequests().pipe(catchError(() => of([]))),
    })
      .pipe(
        finalize(() => {
          this.tabLoading.requests = false;
        })
      )
      .subscribe(({ regs, pend, validationApps, reserveRemoval, reserveReferentRequests }) => {
        this.registrations = regs;
        this.pending = pend;
        this.validationApplications = validationApps;
        this.reserveRemovalRequests = reserveRemoval;
        this.reserveReferentRequests = reserveReferentRequests;
        this.tabLoaded.requests = true;
      });
  }

  private loadReservesTab(force = false): void {
    if (this.tabLoading.reserves || (!force && this.tabLoaded.reserves)) {
      return;
    }
    this.tabLoading.reserves = true;
    this.api
      .getReferentReserveMembers()
      .pipe(
        catchError(() => of([])),
        finalize(() => {
          this.tabLoading.reserves = false;
        })
      )
      .subscribe((referentReserves) => {
        this.referentReserves = referentReserves;
        if (
          this.referentReserves.length &&
          !this.referentReserves.some((r) => r.reserve.area_code === this.selectedReferentReserveCode)
        ) {
          this.selectedReferentReserveCode = this.referentReserves[0].reserve.area_code;
        }
        this.tabLoaded.reserves = true;
      });
  }

  private loadAppAdminsTab(force = false): void {
    if (this.tabLoading['app-admins'] || (!force && this.tabLoaded['app-admins'])) {
      return;
    }
    this.tabLoading['app-admins'] = true;
    this.api
      .getApplicationAdmins()
      .pipe(
        catchError(() => of(null)),
        finalize(() => {
          this.tabLoading['app-admins'] = false;
        })
      )
      .subscribe((appAdmins) => {
        this.appAdminAvailable = Array.isArray(appAdmins);
        this.appAdminRows = Array.isArray(appAdmins) ? appAdmins : [];
        this.tabLoaded['app-admins'] = true;
      });
  }


  onUserAccessSearchInput(): void {
    const query = (this.userAccessSearchQuery || '').trim();
    if (query.length < 2) {
      this.userAccessSuggestions = [];
      return;
    }
    this.userAccessSearchLoading = true;
    this.api.searchKeycloakUsers(query).subscribe({
      next: (rows) => {
        this.userAccessSuggestions = rows || [];
      },
      error: () => {
        this.userAccessSuggestions = [];
      },
      complete: () => {
        this.userAccessSearchLoading = false;
      },
    });
  }

  selectUserForAccess(user: KeycloakUserSuggestionDto): void {
    this.selectedUserAccessSub = user.keycloak_sub;
    this.selectedUserAccessLabel = user.label || user.email;
    this.userAccessSearchQuery = this.selectedUserAccessLabel;
    this.userAccessSuggestions = [];
    this.loadUserAccessForSelectedUser();
  }

  onUserAccessToggle(slug: string, checked: boolean): void {
    const row = this.userAccessData?.applications.find((r) => r.application.slug === slug);
    if (!row?.editable) {
      return;
    }
    this.userAccessDraft[slug] = checked;
  }

  isUserAccessChecked(row: UserApplicationAccessRowDto): boolean {
    const slug = row.application.slug;
    if (slug in this.userAccessDraft) {
      return !!this.userAccessDraft[slug];
    }
    return row.has_access;
  }

  saveUserApplicationAccess(): void {
    if (!this.selectedUserAccessSub || this.userAccessSaving) {
      return;
    }
    const editable = (this.userAccessData?.applications || []).filter((r) => r.editable);
    const access: Record<string, boolean> = {};
    for (const row of editable) {
      access[row.application.slug] = this.isUserAccessChecked(row);
    }
    this.userAccessSaving = true;
    this.userAccessLoadError = '';
    this.api.updateUserApplicationAccess(this.selectedUserAccessSub, access).subscribe({
      next: (data) => {
        this.userAccessData = data;
        this.userAccessDraft = {};
        this.tabLoaded['user-access'] = true;
      },
      error: (err) => {
        this.userAccessLoadError = err?.error?.detail || 'Enregistrement impossible.';
      },
      complete: () => {
        this.userAccessSaving = false;
      },
    });
  }

  private loadUserAccessTab(force = false): void {
    if (this.tabLoading['user-access'] || (!force && this.tabLoaded['user-access'] && !this.selectedUserAccessSub)) {
      return;
    }
    this.tabLoading['user-access'] = true;
    if (!this.selectedUserAccessSub) {
      this.tabLoading['user-access'] = false;
      this.tabLoaded['user-access'] = true;
      return;
    }
    this.loadUserAccessForSelectedUser(force);
  }

  private loadUserAccessForSelectedUser(force = false): void {
    if (!this.selectedUserAccessSub) {
      return;
    }
    this.tabLoading['user-access'] = true;
    this.userAccessLoadError = '';
    this.api.getUserApplicationAccess(this.selectedUserAccessSub).subscribe({
      next: (data) => {
        this.userAccessData = data;
        this.userAccessDraft = {};
        this.tabLoaded['user-access'] = true;
      },
      error: (err) => {
        this.userAccessData = null;
        this.userAccessLoadError = err?.error?.detail || 'Chargement impossible.';
      },
      complete: () => {
        this.tabLoading['user-access'] = false;
      },
    });
  }

  private reloadAppAdmins(): void {
    this.api.getApplicationAdmins().subscribe({
      next: (rows) => {
        this.appAdminRows = rows;
        this.tabLoaded['app-admins'] = true;
        this.appAdminActionKey = null;
      },
      error: () => {
        this.appAdminActionKey = null;
      },
    });
  }
}
