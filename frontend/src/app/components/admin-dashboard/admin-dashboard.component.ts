import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize, map, switchMap } from 'rxjs/operators';
import { ImageCroppedEvent, base64ToFile } from 'ngx-image-cropper';
import {
  AdminReserveReferentRequestDto,
  AdminReserveMemberRemovalRequestDto,
  ApiService,
  ApplicationDto,
  ApplicationMemberDto,
  ApplicationAdminUserDto,
  KeycloakUserSuggestionDto,
  UserApplicationAccessDto,
  UserApplicationAccessRowDto,
  ReferentReserveMembersRowDto,
} from 'src/app/services/api.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import {
  APPLICATION_IMAGE_ASPECT_RATIO,
  APPLICATION_IMAGE_HEIGHT,
  APPLICATION_IMAGE_WIDTH,
} from 'src/app/constants/application-image.constants';
import { applicationImageUrl } from 'src/app/utils/application-image.util';

@Component({
  selector: 'app-admin-dashboard',
  templateUrl: './admin-dashboard.component.html',
  styleUrls: ['./admin-dashboard.component.scss'],
})
export class AdminDashboardComponent implements OnInit {
  @ViewChild('catalogImageInput') catalogImageInput?: ElementRef<HTMLInputElement>;
  activeTab: 'requests' | 'reserves' | 'user-access' | 'applications' = 'requests';
  tabLoading: Record<'requests' | 'reserves' | 'user-access' | 'applications', boolean> = {
    requests: false,
    reserves: false,
    'user-access': false,
    applications: false,
  };
  tabLoaded: Record<'requests' | 'reserves' | 'user-access' | 'applications', boolean> = {
    requests: false,
    reserves: false,
    'user-access': false,
    applications: false,
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
  catalogApplications: ApplicationDto[] = [];
  catalogCountsRefreshing = false;
  catalogCountsRefreshError = '';
  catalogEditingSlug = '';
  catalogForm: ApplicationDto = this.emptyCatalogForm();
  catalogSaving = false;
  catalogFormError = '';
  catalogModalOpen = false;
  catalogImageUploading = false;
  catalogImageCacheBust = Date.now();
  catalogCropModalOpen = false;
  catalogCropImageFile: File | null = null;
  catalogCroppedFile: File | null = null;
  catalogCropLoadError = '';
  catalogMembersModalOpen = false;
  catalogMembersApp: ApplicationDto | null = null;
  catalogMembersDraft: ApplicationMemberDto[] = [];
  catalogAvailableDraft: ApplicationMemberDto[] = [];
  catalogMembersInitialSubs: string[] = [];
  catalogMembers: ApplicationMemberDto[] = [];
  catalogMembersTotal = 0;
  catalogMembersPage = 1;
  catalogMembersPageSize = 10;
  catalogMembersTotalPages = 0;
  catalogMembersSearchQuery = '';
  catalogMembersSelected: Record<string, boolean> = {};
  catalogAvailableMembers: ApplicationMemberDto[] = [];
  catalogAvailableTotal = 0;
  catalogAvailablePage = 1;
  catalogAvailablePageSize = 10;
  catalogAvailableTotalPages = 0;
  catalogAvailableSearchQuery = '';
  catalogAvailableSelected: Record<string, boolean> = {};
  catalogMembersError = '';
  catalogMembersDataLoading = false;
  catalogMembersSaving = false;
  catalogAdminDraft: ApplicationAdminUserDto[] = [];
  catalogAdminSearchQuery = '';
  catalogAdminSuggestions: KeycloakUserSuggestionDto[] = [];
  catalogAdminSearchLoading = false;

  readonly applicationImageWidth = APPLICATION_IMAGE_WIDTH;
  readonly applicationImageHeight = APPLICATION_IMAGE_HEIGHT;
  readonly applicationImageAspectRatio = APPLICATION_IMAGE_ASPECT_RATIO;

  constructor(private api: ApiService, private auth: AuthService) {}

  ngOnInit(): void {
    const me = this.auth.getMeSnapshot();
    this.isSuperAdmin = !!me?.profile?.is_super_admin;
    this.isReserveReferent = !!me?.is_reserve_referent || !!me?.reserves?.some((r) => !!r.referent);
    if (!this.canShowRequestsTab && this.canShowReservesTab) {
      this.activeTab = 'reserves';
    } else if (!this.canShowRequestsTab && this.activeTab === 'requests') {
      this.activeTab = this.canShowApplicationsTab ? 'applications' : 'requests';
    }
    if (!this.canShowReservesTab && this.activeTab === 'reserves') {
      this.activeTab = this.canShowRequestsTab ? 'requests' : 'applications';
    }
    if (!this.canShowApplicationsTab && this.activeTab === 'applications') {
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

  setActiveTab(tab: 'requests' | 'reserves' | 'user-access' | 'applications'): void {
    if (tab === 'requests' && !this.canShowRequestsTab) {
      return;
    }
    if (tab === 'reserves' && !this.canShowReservesTab) {
      return;
    }
    if (tab === 'user-access' && !this.canShowUserAccessTab) {
      return;
    }
    if (tab === 'applications' && !this.canShowApplicationsTab) {
      return;
    }
    this.activeTab = tab;
    this.loadTab(tab);
  }

  get canShowReservesTab(): boolean {
    return this.isSuperAdmin || this.isReserveReferent;
  }

  get canShowUserAccessTab(): boolean {
    return this.isSuperAdmin;
  }

  get canShowApplicationsTab(): boolean {
    return this.isSuperAdmin;
  }

  get canShowRequestsTab(): boolean {
    return this.isSuperAdmin || this.canValidateApplications;
  }

  get visibleTabsCount(): number {
    return [
      this.canShowRequestsTab,
      this.canShowReservesTab,
      this.canShowUserAccessTab,
      this.canShowApplicationsTab,
    ].filter(Boolean).length;
  }

  isTabLoading(tab: 'requests' | 'reserves' | 'user-access' | 'applications'): boolean {
    return this.tabLoading[tab];
  }

  private loadTab(tab: 'requests' | 'reserves' | 'user-access' | 'applications', force = false): void {
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
    if (tab === 'applications') {
      this.loadApplicationsTab(force);
    }
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

  private emptyCatalogForm(): ApplicationDto {
    return {
      slug: '',
      nom: '',
      url: '',
      image: '',
      description: '',
      managed_by_si: true,
      requires_access_request: true,
      keycloak_client_id: '',
    };
  }

  startNewCatalogApplication(): void {
    this.catalogEditingSlug = '';
    this.catalogForm = this.emptyCatalogForm();
    this.catalogFormError = '';
    this.catalogAdminDraft = [];
    this.catalogAdminSearchQuery = '';
    this.catalogAdminSuggestions = [];
  }

  openCatalogModalForNew(): void {
    this.startNewCatalogApplication();
    this.catalogModalOpen = true;
  }

  editCatalogApplication(app: ApplicationDto): void {
    this.catalogEditingSlug = app.slug;
    this.catalogForm = {
      slug: app.slug,
      nom: app.nom,
      url: app.url || '',
      image: app.image || '',
      description: app.description || '',
      managed_by_si: !!app.managed_by_si,
      requires_access_request: app.requires_access_request !== false,
      keycloak_client_id: app.keycloak_client_id || '',
    };
    this.catalogFormError = '';
    this.catalogAdminSearchQuery = '';
    this.catalogAdminSuggestions = [];
    this.loadCatalogAdmins(app.slug);
  }

  openCatalogModalForEdit(app: ApplicationDto): void {
    this.editCatalogApplication(app);
    this.catalogModalOpen = true;
  }

  closeCatalogModal(): void {
    this.catalogModalOpen = false;
    this.catalogFormError = '';
  }

  applicationImageUrl(image?: string): string {
    return applicationImageUrl(image, this.catalogImageCacheBust);
  }

  formatApplicationMemberCount(app: ApplicationDto): string {
    if (!app.managed_by_si) {
      return '—';
    }
    if (!app.requires_access_request) {
      return 'Tous';
    }
    if (app.member_count == null) {
      return '—';
    }
    return String(app.member_count);
  }

  formatApplicationAdminCount(app: ApplicationDto): string {
    if (!app.managed_by_si || !app.requires_access_request) {
      return '—';
    }
    if (app.admin_count == null) {
      return '—';
    }
    return String(app.admin_count);
  }

  formatCountsUpdatedAtLabel(isoDate: string): string {
    const date = new Date(isoDate);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    return date.toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  get catalogCountsUpdatedAtLabel(): string {
    const timestamps = this.catalogApplications
      .map((app) => app.counts_updated_at)
      .filter((value): value is string => !!value);
    if (!timestamps.length) {
      return 'Jamais actualisé';
    }
    const latest = timestamps.reduce((max, current) => (current > max ? current : max));
    return this.formatCountsUpdatedAtLabel(latest);
  }

  refreshCatalogCounts(): void {
    if (this.catalogCountsRefreshing) {
      return;
    }
    this.catalogCountsRefreshing = true;
    this.catalogCountsRefreshError = '';
    this.api.refreshApplicationCatalogCounts().subscribe({
      next: (payload) => {
        const apps = 'applications' in payload ? payload.applications : [];
        if (apps.length) {
          const bySlug = new Map(apps.map((a) => [a.slug, a]));
          this.catalogApplications = this.catalogApplications.map(
            (app) => bySlug.get(app.slug) ?? app
          );
        }
      },
      error: (err) => {
        this.catalogCountsRefreshError =
          err?.error?.detail || 'Impossible d’actualiser les effectifs Keycloak.';
      },
      complete: () => {
        this.catalogCountsRefreshing = false;
      },
    });
  }

  canManageApplicationMembers(app: ApplicationDto): boolean {
    return !!app.managed_by_si && !!app.requires_access_request;
  }

  get canManageCatalogAdmins(): boolean {
    return !!this.catalogForm.managed_by_si && !!this.catalogForm.requires_access_request;
  }

  loadCatalogAdmins(slug: string): void {
    if (!slug) {
      this.catalogAdminDraft = [];
      return;
    }
    this.api.getCatalogApplicationAdmins(slug).subscribe({
      next: (admins) => {
        this.catalogAdminDraft = admins || [];
      },
      error: () => {
        this.catalogAdminDraft = [];
      },
    });
  }

  onCatalogAdminSearchInput(): void {
    const query = (this.catalogAdminSearchQuery || '').trim();
    if (query.length < 2) {
      this.catalogAdminSuggestions = [];
      return;
    }
    this.catalogAdminSearchLoading = true;
    this.api.searchKeycloakUsers(query).subscribe({
      next: (rows) => {
        const existing = new Set(this.catalogAdminDraft.map((a) => a.keycloak_sub));
        this.catalogAdminSuggestions = (rows || []).filter((row) => !existing.has(row.keycloak_sub));
      },
      error: () => {
        this.catalogAdminSuggestions = [];
      },
      complete: () => {
        this.catalogAdminSearchLoading = false;
      },
    });
  }

  addCatalogAdminFromSuggestion(suggestion: KeycloakUserSuggestionDto): void {
    if (this.catalogAdminDraft.some((a) => a.keycloak_sub === suggestion.keycloak_sub)) {
      return;
    }
    this.catalogAdminDraft = [
      ...this.catalogAdminDraft,
      {
        keycloak_sub: suggestion.keycloak_sub,
        email: suggestion.email,
        first_name: suggestion.first_name,
        last_name: suggestion.last_name,
      },
    ];
    this.catalogAdminSearchQuery = '';
    this.catalogAdminSuggestions = [];
  }

  removeCatalogAdmin(userSub: string): void {
    this.catalogAdminDraft = this.catalogAdminDraft.filter((a) => a.keycloak_sub !== userSub);
  }

  formatCatalogAdminLabel(admin: ApplicationAdminUserDto): string {
    const fullName = `${admin.first_name || ''} ${admin.last_name || ''}`.trim();
    if (fullName) {
      return `${fullName} (${admin.email})`;
    }
    return admin.email;
  }

  openCatalogMembersModal(app: ApplicationDto): void {
    if (!this.canManageApplicationMembers(app)) {
      return;
    }
    this.catalogMembersApp = app;
    this.catalogMembersModalOpen = true;
    this.catalogMembersPage = 1;
    this.catalogAvailablePage = 1;
    this.catalogMembersSearchQuery = '';
    this.catalogAvailableSearchQuery = '';
    this.catalogMembersSelected = {};
    this.catalogAvailableSelected = {};
    this.catalogMembersError = '';
    this.loadCatalogMembersData();
  }

  closeCatalogMembersModal(): void {
    if (this.hasCatalogMembersPendingChanges) {
      const discard = window.confirm('Des modifications ne sont pas enregistrées. Fermer quand même ?');
      if (!discard) {
        return;
      }
    }
    this.catalogMembersModalOpen = false;
    this.catalogMembersApp = null;
    this.catalogMembersDraft = [];
    this.catalogAvailableDraft = [];
    this.catalogMembersInitialSubs = [];
    this.catalogMembers = [];
    this.catalogAvailableMembers = [];
    this.catalogMembersError = '';
    this.catalogMembersSelected = {};
    this.catalogAvailableSelected = {};
    this.catalogMembersSaving = false;
  }

  onCatalogMembersSearchInput(): void {
    this.catalogMembersPage = 1;
    this.catalogMembersSelected = {};
    this.refreshCatalogMemberViews();
  }

  onCatalogAvailableSearchInput(): void {
    this.catalogAvailablePage = 1;
    this.catalogAvailableSelected = {};
    this.refreshCatalogMemberViews();
  }

  goCatalogMembersPage(page: number): void {
    if (page < 1 || (this.catalogMembersTotalPages && page > this.catalogMembersTotalPages)) {
      return;
    }
    this.catalogMembersPage = page;
    this.catalogMembersSelected = {};
    this.refreshCatalogMemberViews();
  }

  goCatalogAvailablePage(page: number): void {
    if (page < 1 || (this.catalogAvailableTotalPages && page > this.catalogAvailableTotalPages)) {
      return;
    }
    this.catalogAvailablePage = page;
    this.catalogAvailableSelected = {};
    this.refreshCatalogMemberViews();
  }

  loadCatalogMembersData(): void {
    const app = this.catalogMembersApp;
    if (!app) {
      return;
    }
    this.catalogMembersDataLoading = true;
    this.catalogMembersError = '';
    this.api.getApplicationDualMembers(app.slug).subscribe({
      next: (data) => {
        this.catalogMembersDraft = [...(data.members || [])];
        this.catalogAvailableDraft = [...(data.available || [])];
        this.catalogMembersInitialSubs = this.catalogMembersDraft.map((m) => m.keycloak_sub);
        this.refreshCatalogMemberViews();
      },
      error: () => {
        this.catalogMembersError = 'Impossible de charger les utilisateurs.';
        this.catalogMembersDraft = [];
        this.catalogAvailableDraft = [];
        this.refreshCatalogMemberViews();
      },
      complete: () => {
        this.catalogMembersDataLoading = false;
      },
    });
  }

  refreshCatalogMemberViews(): void {
    const availableView = this.paginateCatalogMembers(
      this.filterCatalogMembers(this.catalogAvailableDraft, this.catalogAvailableSearchQuery),
      this.catalogAvailablePage,
      this.catalogAvailablePageSize
    );
    this.catalogAvailableMembers = availableView.items;
    this.catalogAvailableTotal = availableView.total;
    this.catalogAvailableTotalPages = availableView.totalPages;
    if (this.catalogAvailableTotalPages && this.catalogAvailablePage > this.catalogAvailableTotalPages) {
      this.catalogAvailablePage = this.catalogAvailableTotalPages;
      this.refreshCatalogMemberViews();
      return;
    }

    const membersView = this.paginateCatalogMembers(
      this.filterCatalogMembers(this.catalogMembersDraft, this.catalogMembersSearchQuery),
      this.catalogMembersPage,
      this.catalogMembersPageSize
    );
    this.catalogMembers = membersView.items;
    this.catalogMembersTotal = membersView.total;
    this.catalogMembersTotalPages = membersView.totalPages;
    if (this.catalogMembersTotalPages && this.catalogMembersPage > this.catalogMembersTotalPages) {
      this.catalogMembersPage = this.catalogMembersTotalPages;
      this.refreshCatalogMemberViews();
    }
  }

  private filterCatalogMembers(rows: ApplicationMemberDto[], query: string): ApplicationMemberDto[] {
    const q = (query || '').trim().toLowerCase();
    if (!q) {
      return [...rows];
    }
    return rows.filter((member) => {
      const haystack = [
        member.email,
        member.first_name,
        member.last_name,
        member.username,
        member.label,
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }

  private paginateCatalogMembers(
    rows: ApplicationMemberDto[],
    page: number,
    pageSize: number
  ): { items: ApplicationMemberDto[]; total: number; totalPages: number } {
    const total = rows.length;
    const totalPages = total ? Math.ceil(total / pageSize) : 0;
    const safePage = totalPages ? Math.min(Math.max(page, 1), totalPages) : 1;
    const start = (safePage - 1) * pageSize;
    return {
      items: rows.slice(start, start + pageSize),
      total,
      totalPages,
    };
  }

  private sortCatalogMembers(rows: ApplicationMemberDto[]): ApplicationMemberDto[] {
    return [...rows].sort((a, b) => {
      const left = `${a.last_name} ${a.first_name} ${a.email}`.toLowerCase();
      const right = `${b.last_name} ${b.first_name} ${b.email}`.toLowerCase();
      return left.localeCompare(right);
    });
  }

  toggleCatalogAvailableSelectAll(checked: boolean): void {
    const next: Record<string, boolean> = {};
    if (checked) {
      for (const member of this.catalogAvailableMembers) {
        next[member.keycloak_sub] = true;
      }
    }
    this.catalogAvailableSelected = next;
  }

  toggleCatalogMembersSelectAll(checked: boolean): void {
    const next: Record<string, boolean> = {};
    if (checked) {
      for (const member of this.catalogMembers) {
        next[member.keycloak_sub] = true;
      }
    }
    this.catalogMembersSelected = next;
  }

  get selectedAvailableCount(): number {
    return Object.values(this.catalogAvailableSelected).filter(Boolean).length;
  }

  get selectedMembersCount(): number {
    return Object.values(this.catalogMembersSelected).filter(Boolean).length;
  }

  get isAllAvailableSelected(): boolean {
    return (
      this.catalogAvailableMembers.length > 0 &&
      this.catalogAvailableMembers.every((m) => !!this.catalogAvailableSelected[m.keycloak_sub])
    );
  }

  get isAllMembersSelected(): boolean {
    return (
      this.catalogMembers.length > 0 &&
      this.catalogMembers.every((m) => !!this.catalogMembersSelected[m.keycloak_sub])
    );
  }

  get hasCatalogMembersPendingChanges(): boolean {
    const currentSubs = new Set(this.catalogMembersDraft.map((m) => m.keycloak_sub));
    const initialSubs = new Set(this.catalogMembersInitialSubs);
    if (currentSubs.size !== initialSubs.size) {
      return true;
    }
    for (const sub of currentSubs) {
      if (!initialSubs.has(sub)) {
        return true;
      }
    }
    return false;
  }

  get catalogMembersPendingSummary(): string {
    const currentSubs = new Set(this.catalogMembersDraft.map((m) => m.keycloak_sub));
    const initialSubs = new Set(this.catalogMembersInitialSubs);
    const toAdd = [...currentSubs].filter((sub) => !initialSubs.has(sub)).length;
    const toRemove = [...initialSubs].filter((sub) => !currentSubs.has(sub)).length;
    const parts: string[] = [];
    if (toAdd) {
      parts.push(`+${toAdd}`);
    }
    if (toRemove) {
      parts.push(`-${toRemove}`);
    }
    return parts.join(', ');
  }

  private getSelectedSubs(selection: Record<string, boolean>): string[] {
    return Object.entries(selection)
      .filter(([, checked]) => checked)
      .map(([sub]) => sub);
  }

  transferAvailableToMembers(): void {
    const subs = new Set(this.getSelectedSubs(this.catalogAvailableSelected));
    if (!subs.size) {
      return;
    }
    const moving = this.catalogAvailableDraft.filter((m) => subs.has(m.keycloak_sub));
    this.catalogAvailableDraft = this.catalogAvailableDraft.filter((m) => !subs.has(m.keycloak_sub));
    this.catalogMembersDraft = this.sortCatalogMembers([...this.catalogMembersDraft, ...moving]);
    this.catalogAvailableSelected = {};
    this.refreshCatalogMemberViews();
  }

  transferMembersToAvailable(): void {
    const subs = new Set(this.getSelectedSubs(this.catalogMembersSelected));
    if (!subs.size) {
      return;
    }
    const moving = this.catalogMembersDraft.filter((m) => subs.has(m.keycloak_sub));
    this.catalogMembersDraft = this.catalogMembersDraft.filter((m) => !subs.has(m.keycloak_sub));
    this.catalogAvailableDraft = this.sortCatalogMembers([...this.catalogAvailableDraft, ...moving]);
    this.catalogMembersSelected = {};
    this.refreshCatalogMemberViews();
  }

  saveCatalogMembers(): void {
    const app = this.catalogMembersApp;
    if (!app || this.catalogMembersSaving || !this.hasCatalogMembersPendingChanges) {
      return;
    }
    const currentSubs = new Set(this.catalogMembersDraft.map((m) => m.keycloak_sub));
    const initialSubs = new Set(this.catalogMembersInitialSubs);
    const toAdd = [...currentSubs].filter((sub) => !initialSubs.has(sub));
    const toRemove = [...initialSubs].filter((sub) => !currentSubs.has(sub));

    const tasks = [];
    if (toAdd.length) {
      tasks.push(this.api.addApplicationMembers(app.slug, toAdd));
    }
    if (toRemove.length) {
      tasks.push(this.api.removeApplicationMembers(app.slug, toRemove));
    }
    if (!tasks.length) {
      return;
    }

    this.catalogMembersSaving = true;
    this.catalogMembersError = '';
    forkJoin(tasks).subscribe({
      next: () => {
        this.catalogMembersInitialSubs = this.catalogMembersDraft.map((m) => m.keycloak_sub);
      },
      error: (err) => {
        const detail = err?.error?.detail;
        this.catalogMembersError =
          typeof detail === 'string' ? detail : 'Impossible d’enregistrer les modifications.';
      },
      complete: () => {
        this.catalogMembersSaving = false;
      },
    });
  }

  get canManageCatalogImage(): boolean {
    return !!this.catalogEditingSlug;
  }

  onCatalogImageSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file || !this.catalogEditingSlug || this.catalogImageUploading) {
      return;
    }
    if (!file.type.startsWith('image/') || file.type === 'image/svg+xml') {
      this.catalogFormError = 'Seules les images raster (png, jpg, webp, gif) sont acceptées.';
      this.resetCatalogImageInput();
      return;
    }
    this.catalogFormError = '';
    this.catalogCropLoadError = '';
    this.catalogCropImageFile = file;
    this.catalogCroppedFile = null;
    this.catalogCropModalOpen = true;
  }

  onCatalogImageCropped(event: ImageCroppedEvent): void {
    if (!event.base64 || !this.catalogEditingSlug) {
      this.catalogCroppedFile = null;
      return;
    }
    const blob = base64ToFile(event.base64);
    this.catalogCroppedFile = new File([blob], `${this.catalogEditingSlug}.png`, { type: 'image/png' });
  }

  cancelCatalogImageCrop(): void {
    this.catalogCropModalOpen = false;
    this.catalogCropImageFile = null;
    this.catalogCroppedFile = null;
    this.catalogCropLoadError = '';
    this.resetCatalogImageInput();
  }

  onCatalogCropImageFailed(): void {
    this.catalogCropLoadError = 'Impossible de charger cette image. Essayez un fichier PNG ou JPEG.';
    this.catalogCroppedFile = null;
  }

  private resetCatalogImageInput(): void {
    const input = this.catalogImageInput?.nativeElement;
    if (input) {
      input.value = '';
    }
  }

  confirmCatalogImageCrop(): void {
    if (!this.catalogEditingSlug || !this.catalogCroppedFile || this.catalogImageUploading) {
      return;
    }
    const file = this.catalogCroppedFile;
    this.catalogImageUploading = true;
    this.catalogFormError = '';
    this.api.uploadAdminApplicationImage(this.catalogEditingSlug, file).subscribe({
      next: (saved) => {
        this.catalogForm.image = saved.image || '';
        this.catalogImageCacheBust = Date.now();
        this.reloadApplicationsCatalog();
        this.cancelCatalogImageCrop();
      },
      error: (err) => {
        this.catalogFormError = err?.error?.detail || 'Import impossible.';
      },
      complete: () => {
        this.catalogImageUploading = false;
      },
    });
  }

  removeCatalogImage(): void {
    if (!this.catalogEditingSlug || this.catalogImageUploading || !this.catalogForm.image) {
      return;
    }
    this.catalogImageUploading = true;
    this.catalogFormError = '';
    this.api.deleteAdminApplicationImage(this.catalogEditingSlug).subscribe({
      next: (saved) => {
        this.catalogForm.image = saved.image || '';
        this.catalogImageCacheBust = Date.now();
        this.reloadApplicationsCatalog();
      },
      error: (err) => {
        this.catalogFormError = err?.error?.detail || 'Suppression impossible.';
      },
      complete: () => {
        this.catalogImageUploading = false;
      },
    });
  }

  saveCatalogApplication(): void {
    if (this.catalogSaving) {
      return;
    }
    const payload = {
      slug: (this.catalogForm.slug || '').trim(),
      nom: (this.catalogForm.nom || '').trim(),
      url: (this.catalogForm.url || '').trim(),
      description: (this.catalogForm.description || '').trim(),
      managed_by_si: !!this.catalogForm.managed_by_si,
      requires_access_request: !!this.catalogForm.requires_access_request,
      keycloak_client_id: (this.catalogForm.keycloak_client_id || '').trim(),
    };
    if (!payload.nom) {
      this.catalogFormError = 'Le nom est requis.';
      return;
    }
    if (!this.catalogEditingSlug && !payload.slug) {
      this.catalogFormError = 'Le slug est requis pour une nouvelle application.';
      return;
    }

    this.catalogSaving = true;
    this.catalogFormError = '';
    const req = this.catalogEditingSlug
      ? this.api.updateAdminApplication(this.catalogEditingSlug, {
          nom: payload.nom,
          url: payload.url,
          description: payload.description,
          managed_by_si: payload.managed_by_si,
          requires_access_request: payload.requires_access_request,
          keycloak_client_id: payload.keycloak_client_id,
        })
      : this.api.createAdminApplication(payload);

    req.pipe(
      switchMap((saved) => {
        this.catalogEditingSlug = saved.slug;
        this.catalogForm = {
          slug: saved.slug,
          nom: saved.nom,
          url: saved.url || '',
          image: saved.image || '',
          description: saved.description || '',
          managed_by_si: !!saved.managed_by_si,
          requires_access_request: saved.requires_access_request !== false,
          keycloak_client_id: saved.keycloak_client_id || '',
        };
        if (!this.canManageCatalogAdmins) {
          this.catalogAdminDraft = [];
          return of(saved);
        }
        const subs = this.catalogAdminDraft.map((admin) => admin.keycloak_sub);
        return this.api.syncCatalogApplicationAdmins(saved.slug, subs).pipe(map(() => saved));
      })
    ).subscribe({
      next: () => {
        this.reloadApplicationsCatalog();
      },
      error: (err) => {
        const errors = err?.error;
        if (errors && typeof errors === 'object') {
          const firstKey = Object.keys(errors)[0];
          const firstVal = firstKey ? errors[firstKey] : null;
          if (Array.isArray(firstVal) && firstVal.length) {
            this.catalogFormError = String(firstVal[0]);
            return;
          }
          if (typeof firstVal === 'string') {
            this.catalogFormError = firstVal;
            return;
          }
        }
        this.catalogFormError = err?.error?.detail || 'Enregistrement impossible.';
      },
      complete: () => {
        this.catalogSaving = false;
      },
    });
  }

  private loadApplicationsTab(force = false): void {
    if (this.tabLoading.applications || (!force && this.tabLoaded.applications)) {
      return;
    }
    this.tabLoading.applications = true;
    this.api
      .getAdminApplicationCatalog()
      .pipe(
        catchError(() => of([])),
        finalize(() => {
          this.tabLoading.applications = false;
        })
      )
      .subscribe((apps) => {
        this.catalogApplications = apps || [];
        this.tabLoaded.applications = true;
      });
  }

  private reloadApplicationsCatalog(): void {
    this.api.getAdminApplicationCatalog().subscribe({
      next: (apps) => {
        this.catalogApplications = apps || [];
        this.tabLoaded.applications = true;
      },
    });
  }
}
