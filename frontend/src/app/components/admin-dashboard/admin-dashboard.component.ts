import { Component, OnInit } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';
import { ApiService } from 'src/app/services/api.service';

@Component({
  selector: 'app-admin-dashboard',
  templateUrl: './admin-dashboard.component.html',
})
export class AdminDashboardComponent implements OnInit {
  registrations: { public_id: string; status: string; email: string }[] = [];
  pending: {
    kind: string;
    item_id: number;
    applicant_email: string;
    application: { nom: string; slug: string };
    request_justification?: string;
  }[] = [];
  loading = true;
  decisionLoadingKey: string | null = null;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    forkJoin({
      regs: this.api.getAdminRegistrations().pipe(catchError(() => of([]))),
      pend: this.api.getPendingItems().pipe(catchError(() => of([]))),
    })
      .pipe(finalize(() => (this.loading = false)))
      .subscribe(({ regs, pend }) => {
        this.registrations = regs;
        this.pending = pend;
      });
  }

  approveReg(id: string) {
    this.api.superApprove(id).subscribe(() => this.ngOnInit());
  }

  rejectReg(id: string) {
    this.api.superReject(id).subscribe(() => this.ngOnInit());
  }

  decide(itemId: number, kind: string, approve: boolean) {
    const key = `${kind}:${itemId}:${approve ? 'approve' : 'reject'}`;
    this.decisionLoadingKey = key;
    const obs =
      kind === 'additional'
        ? this.api.decideAdditionalItem(itemId, approve)
        : this.api.decideRegistrationItem(itemId, approve);
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
}
