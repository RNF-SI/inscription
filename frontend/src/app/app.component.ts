import { Component, OnInit, inject } from '@angular/core';

import { MatomoService } from './services/matomo.service';

@Component({
  standalone: false,
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit {
  title = 'inscription';

  private readonly matomo = inject(MatomoService);

  ngOnInit(): void {
    // Mesure d'audience : un seul démarrage, pour toute la durée de vie de
    // l'application (cf. services/matomo.service.ts).
    this.matomo.start();
  }
}
