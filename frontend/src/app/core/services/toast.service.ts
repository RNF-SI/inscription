import { Injectable } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';

import { ToastComponent, ToastData, ToastNiveau } from '../components/toast/toast.component';

/** Options ponctuelles d'un toast ; le reste vient des valeurs par défaut. */
export interface ToastOptions {
  /** Durée d'affichage en millisecondes ; 0 laisse le toast jusqu'à fermeture manuelle. */
  duree?: number;
}

/** Durée reprise de l'ancienne configuration globale des toasts. */
const DUREE_PAR_DEFAUT = 15000;

/**
 * Affiche les messages transitoires de l'application via MatSnackBar.
 *
 * Les quatre méthodes gardent la signature de l'API historique
 * (message puis titre, tous deux déjà traduits) afin que les appelants
 * n'aient eu à changer que le type injecté.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  constructor(private readonly snackBar: MatSnackBar) {}

  success(message: string, titre?: string, options?: ToastOptions): void {
    this.ouvrir('success', message, titre, options);
  }

  error(message: string, titre?: string, options?: ToastOptions): void {
    this.ouvrir('error', message, titre, options);
  }

  warning(message: string, titre?: string, options?: ToastOptions): void {
    this.ouvrir('warning', message, titre, options);
  }

  info(message: string, titre?: string, options?: ToastOptions): void {
    this.ouvrir('info', message, titre, options);
  }

  private ouvrir(
    niveau: ToastNiveau,
    message: string,
    titre?: string,
    options?: ToastOptions
  ): void {
    const config: MatSnackBarConfig<ToastData> = {
      data: { niveau, message, titre: titre || undefined },
      duration: options?.duree ?? DUREE_PAR_DEFAUT,
      panelClass: ['rnf-toast', `rnf-toast--${niveau}`],
      horizontalPosition: 'center',
      verticalPosition: 'top',
      // Une erreur doit être annoncée tout de suite, le reste peut attendre
      // une pause du lecteur d'écran.
      politeness: niveau === 'error' ? 'assertive' : 'polite',
    };

    this.snackBar.openFromComponent(ToastComponent, config);
  }
}
