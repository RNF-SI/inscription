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
  ReferentReserveMembersRowDto,
} from 'src/app/services/api.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';

@Component({
  selector: 'app-admin-dashboard',
  templateUrl: './admin-dashboard.component.html',
})
export class AdminDashboardComponent implements OnInit {
  activeTab: 'requests' | 'reserves' | 'app-admins' = 'requests';
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
  loading = true;
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

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnInit(): void {
    this.isSuperAdmin = !!this.auth.getMeSnapshot()?.profile?.is_super_admin;
    forkJoin({
      regs: this.api.getAdminRegistrations().pipe(catchError(() => of([]))),
      pend: this.api.getPendingItems().pipe(catchError(() => of([]))),
      validationApps: this.api.getMyValidationApplications().pipe(catchError(() => of([]))),
      appAdmins: this.api.getApplicationAdmins().pipe(catchError(() => of(null))),
      reserveRemoval: this.api.getAdminReserveMemberRemovalRequests().pipe(catchError(() => of([]))),
      referentReserves: this.api.getReferentReserveMembers().pipe(catchError(() => of([]))),
      reserveReferentRequests: this.api.getAdminReserveReferentRequests().pipe(catchError(() => of([]))),
    })
      .pipe(finalize(() => (this.loading = false)))
      .subscribe(({ regs, pend, validationApps, appAdmins, reserveRemoval, referentReserves, reserveReferentRequests }) => {
        this.registrations = regs;
        this.pending = pend;
        this.validationApplications = validationApps;
        this.appAdminAvailable = Array.isArray(appAdmins);
        this.appAdminRows = Array.isArray(appAdmins) ? appAdmins : [];
        this.reserveRemovalRequests = reserveRemoval;
        this.referentReserves = referentReserves;
        if (
          this.referentReserves.length &&
          !this.referentReserves.some((r) => r.reserve.area_code === this.selectedReferentReserveCode)
        ) {
          this.selectedReferentReserveCode = this.referentReserves[0].reserve.area_code;
        }
        this.reserveReferentRequests = reserveReferentRequests;
      });
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
    this.api.superApprove(id).subscribe(() => this.ngOnInit());
  }

  rejectReg(id: string) {
    this.api.superReject(id).subscribe(() => this.ngOnInit());
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
      next: () => this.ngOnInit(),
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
      next: () => this.ngOnInit(),
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
        this.ngOnInit();
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
      next: () => this.ngOnInit(),
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
        this.ngOnInit();
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
      next: () => this.ngOnInit(),
      error: () => {
        this.reserveReferentLoadingKey = null;
      },
    });
  }

  isReserveReferentLoading(reqId: number, approve: boolean): boolean {
    return this.reserveReferentLoadingKey === `${reqId}:${approve ? 'approve' : 'reject'}`;
  }

  setActiveTab(tab: 'requests' | 'reserves' | 'app-admins'): void {
    this.activeTab = tab;
  }

  private reloadAppAdmins(): void {
    this.api.getApplicationAdmins().subscribe({
      next: (rows) => {
        this.appAdminRows = rows;
        this.appAdminActionKey = null;
      },
      error: () => {
        this.appAdminActionKey = null;
      },
    });
  }
}
