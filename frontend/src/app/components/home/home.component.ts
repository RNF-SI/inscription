import { Component, OnInit, TemplateRef, ViewChild } from '@angular/core';
import { faArrowUpRightFromSquare, faBan, faCheck, faClock, faKey, faUserPlus } from '@fortawesome/free-solid-svg-icons';
import { User } from '../../home-rnf/models/user.model';
import { AuthService } from '../../home-rnf/services/auth-service.service';
import { Organisme } from '../../models/models';
import { ApiService, ApplicationDto, MeApplicationRow } from 'src/app/services/api.service';
import { ToastrService } from 'ngx-toastr';
import { NgbModal, NgbModalRef } from '@ng-bootstrap/ng-bootstrap';
import { applicationImageUrl } from 'src/app/utils/application-image.util';

export type HomeAccessFilter = 'all' | 'with_access' | 'without_access';
export type HomeManagementFilter = 'all' | 'si' | 'independent';

export type HomeApplication = ApplicationDto & { access_status?: string };

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss'],
})
export class HomeComponent implements OnInit {
  @ViewChild('accessRequestModal') accessRequestModal!: TemplateRef<unknown>;

  constructor(
    private _authService: AuthService,
    private api: ApiService,
    private toastr: ToastrService,
    private modalService: NgbModal
  ) {}

  protected organismes: Organisme[];
  faKey = faKey;
  faUserPlus = faUserPlus;
  faArrowUpRightFromSquare = faArrowUpRightFromSquare;
  faCheck = faCheck;
  faClock = faClock;
  faBan = faBan;

  readonly applicationImageUrl = applicationImageUrl;

  applications: HomeApplication[] = [];
  applicationsLoading = true;
  accessFilter: HomeAccessFilter = 'all';
  managementFilter: HomeManagementFilter = 'all';
  loadingRequestBySlug: { [slug: string]: boolean } = {};
  selectedRequestApp: HomeApplication | null = null;
  requestJustification = '';
  private accessRequestModalRef: NgbModalRef | null = null;

  ngOnInit(): void {
    this.logDecodedTokensForDebug();

    const load = () =>
      this.api.getApplications().subscribe({
        next: (apps) => {
          this.applications = apps;
          this.mergeAccessStatus();
        },
        error: () => {
          this.applications = [];
        },
      }).add(() => {
        this.applicationsLoading = false;
      });

    if (this._authService.authenticated) {
      this._authService.refreshMeFromApi().subscribe({
        next: () => load(),
        error: () => load(),
      });
    } else {
      load();
    }
  }

  private mergeAccessStatus(): void {
    const me = this._authService.getMeSnapshot();
    if (!me?.applications?.length) {
      this.applications = this.applications.map((app) => ({
        ...app,
        access_status: app.access_status || 'none',
      }));
      return;
    }
    const map = new Map<string, string>();
    me.applications.forEach((row: MeApplicationRow) => {
      map.set(row.application.slug, row.access_status);
    });
    this.applications = this.applications.map((a) => ({
      ...a,
      access_status: map.get(a.slug) || 'none',
    }));
  }

  get filteredApplications(): HomeApplication[] {
    return this.applications.filter((app) => this.matchesApplicationFilters(app));
  }

  hasActiveApplicationFilters(): boolean {
    return this.accessFilter !== 'all' || this.managementFilter !== 'all';
  }

  setAccessFilter(filter: HomeAccessFilter): void {
    this.accessFilter = filter;
  }

  setManagementFilter(filter: HomeManagementFilter): void {
    this.managementFilter = filter;
  }

  resetApplicationFilters(): void {
    this.accessFilter = 'all';
    this.managementFilter = 'all';
  }

  hasApplicationAccess(app: HomeApplication): boolean {
    return (app.access_status || 'none') === 'active';
  }

  private matchesApplicationFilters(app: HomeApplication): boolean {
    if (this.managementFilter === 'si' && !app.managed_by_si) {
      return false;
    }
    if (this.managementFilter === 'independent' && app.managed_by_si) {
      return false;
    }
    if (this.user && this.accessFilter !== 'all') {
      const hasAccess = this.hasApplicationAccess(app);
      if (this.accessFilter === 'with_access' && !hasAccess) {
        return false;
      }
      if (this.accessFilter === 'without_access' && hasAccess) {
        return false;
      }
    }
    return true;
  }

  statusIcon(app: HomeApplication) {
    const s = app.access_status || 'none';
    if (s === 'active') {
      return this.faCheck;
    }
    if (s === 'pending' || s === 'revoked') {
      return s === 'pending' ? this.faClock : this.faBan;
    }
    return null;
  }

  statusLabel(app: HomeApplication): string {
    const s = app.access_status || 'none';
    if (s === 'active') {
      return 'Accès accordé';
    }
    if (s === 'pending') {
      return 'Demande en cours';
    }
    if (s === 'revoked') {
      return 'Accès révoqué';
    }
    return 'Pas d’accès';
  }

  statusClass(app: HomeApplication): string {
    const s = app.access_status || 'none';
    if (s === 'active') {
      return 'status-active';
    }
    if (s === 'pending') {
      return 'status-pending';
    }
    if (s === 'revoked') {
      return 'status-revoked';
    }
    return 'status-none';
  }

  canRequestAccess(app: HomeApplication): boolean {
    if (!this.user) {
      return false;
    }
    if (!app.managed_by_si) {
      return false;
    }
    if (!app.requires_access_request) {
      return false;
    }
    const s = app.access_status || 'none';
    return s === 'none' || s === 'revoked';
  }

  requestAccess(app: HomeApplication) {
    if (!this.canRequestAccess(app)) {
      return;
    }
    this.selectedRequestApp = app;
    this.requestJustification = '';
    this.accessRequestModalRef = this.modalService.open(this.accessRequestModal, {
      centered: true,
      backdrop: 'static',
      size: 'lg',
    });
  }

  submitAccessRequest(): void {
    const app = this.selectedRequestApp;
    if (!app || !this.canRequestAccess(app)) {
      return;
    }
    const justification = this.requestJustification.trim();
    if (!justification) {
      this.toastr.warning('La justification est obligatoire pour envoyer la demande.', 'Demande d’accès');
      return;
    }
    this.loadingRequestBySlug[app.slug] = true;
    this.api.requestAdditionalAccess([app.slug], justification).subscribe({
      next: () => {
        this.toastr.success('Demande envoyée au validateur.', 'Demande d’accès');
        this.closeAccessRequestModal();
        this._authService.refreshMeFromApi().subscribe({
          next: () => this.mergeAccessStatus(),
          error: () => this.mergeAccessStatus(),
        });
      },
      error: (err) => {
        const msg = err?.error?.detail || err?.error?.msg || 'Impossible d’envoyer la demande.';
        this.toastr.error(msg, 'Demande d’accès');
      },
    }).add(() => {
      this.loadingRequestBySlug[app.slug] = false;
    });
  }

  closeAccessRequestModal(): void {
    if (this.accessRequestModalRef) {
      this.accessRequestModalRef.close();
    }
    this.accessRequestModalRef = null;
    this.selectedRequestApp = null;
    this.requestJustification = '';
  }

  isSubmittingAccessRequest(): boolean {
    if (!this.selectedRequestApp) {
      return false;
    }
    return !!this.loadingRequestBySlug[this.selectedRequestApp.slug];
  }

  public get user(): null | User {
    return this._authService.getCurrentUser();
  }

  private decodeJwtPayload(token: string | null): Record<string, unknown> | null {
    if (!token) {
      return null;
    }
    const parts = token.split('.');
    if (parts.length < 2 || !parts[1]) {
      return null;
    }
    try {
      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
      const json = atob(padded);
      return JSON.parse(json) as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  private logDecodedTokensForDebug(): void {
    const idToken = localStorage.getItem('tk_id_token');
    const accessToken = localStorage.getItem('access_token');
    const idPayload = this.decodeJwtPayload(idToken);
    const accessPayload = this.decodeJwtPayload(accessToken);

    console.groupCollapsed('[Auth debug] Tokens décodés');
    console.log('id_token payload:', idPayload);
    console.log('id_token groups:', idPayload?.['groups']);
    console.log('id_token resource_access:', idPayload?.['resource_access']);
    console.log('access_token payload:', accessPayload);
    console.log('access_token groups:', accessPayload?.['groups']);
    console.log('access_token resource_access:', accessPayload?.['resource_access']);
    console.groupEnd();
  }
}
