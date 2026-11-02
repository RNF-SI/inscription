import { Component, Inject } from '@angular/core';
import { MAT_SNACK_BAR_DATA, MatSnackBarRef } from '@angular/material/snack-bar';

/** Gravité d'un toast : reprend les quatre niveaux de l'API historique. */
export type ToastNiveau = 'success' | 'error' | 'warning' | 'info';

/** Contenu passé au toast par ToastService. */
export interface ToastData {
  niveau: ToastNiveau;
  message: string;
  titre?: string;
}

/**
 * Contenu d'un toast, ouvert par ToastService via MatSnackBar.openFromComponent().
 * La couleur de fond est portée par le conteneur Material (classe
 * `rnf-toast--<niveau>`, cf. src/styles/toast.scss) : ce composant ne dessine
 * que l'icône, le texte et le bouton de fermeture.
 */
@Component({
  standalone: false,
  selector: 'app-toast',
  templateUrl: './toast.component.html',
  styleUrls: ['./toast.component.scss']
})
export class ToastComponent {
  private static readonly ICONES: Record<ToastNiveau, string> = {
    success: 'check_circle',
    error: 'error',
    warning: 'warning',
    info: 'info',
  };

  constructor(
    @Inject(MAT_SNACK_BAR_DATA) public readonly data: ToastData,
    private readonly snackBarRef: MatSnackBarRef<ToastComponent>
  ) {}

  get icone(): string {
    return ToastComponent.ICONES[this.data.niveau];
  }

  fermer(): void {
    this.snackBarRef.dismiss();
  }
}
