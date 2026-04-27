import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ApiService, MeResponse } from 'src/app/services/api.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';

@Component({
  selector: 'app-moncompte',
  templateUrl: './moncompte.component.html',
  styleUrls: ['./moncompte.component.scss'],
})
export class MoncompteComponent implements OnInit {
  form: UntypedFormGroup;
  me: MeResponse | null = null;
  notifications: { id: number; title: string; body: string; read: boolean }[] = [];
  extraSlugs = '';
  extraRemarks = '';

  constructor(private fb: UntypedFormBuilder, private auth: AuthService, private api: ApiService) {}

  ngOnInit(): void {
    this.form = this.fb.group({
      identifiant: [{ value: '', disabled: true }],
      nom_role: [{ value: '', disabled: true }],
      prenom_role: [{ value: '', disabled: true }],
      organisme: [{ value: '', disabled: true }],
      email: [{ value: '', disabled: true }],
      remarques: [{ value: '', disabled: true }],
    });
    this.api.getMe().subscribe({
      next: (me) => {
        this.me = me;
        localStorage.setItem('me_snapshot', JSON.stringify(me));
        const p = me.profile;
        this.form.patchValue({
          identifiant: p.username || '',
          nom_role: p.last_name || '',
          prenom_role: p.first_name || '',
          organisme: '',
          email: p.email || '',
          remarques: '',
        });
      },
    });
    this.api.getNotifications().subscribe({
      next: (n) => (this.notifications = n),
      error: () => (this.notifications = []),
    });
  }

  markRead(id: number) {
    this.api.markNotificationRead(id).subscribe(() => {
      this.api.getNotifications().subscribe((n) => (this.notifications = n));
    });
  }

  sendAdditional() {
    const slugs = this.extraSlugs
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (!slugs.length) {
      return;
    }
    this.api.requestAdditionalAccess(slugs, this.extraRemarks).subscribe(() => {
      this.extraSlugs = '';
      this.extraRemarks = '';
      this.auth.refreshMeFromApi().subscribe();
    });
  }
}
