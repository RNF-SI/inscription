import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of, throwError } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { AppConfig } from 'src/conf/app.config';

export type ContactMessagePayload = {
  email: string;
  subject: string;
  message: string;
  name?: string;
};

type ContactConfig = {
  apiUrl?: string;
  recipientEmail?: string;
};

/**
 * Envoi d'un message au support, mutualisé entre les applications RNF.
 *
 * La route est hébergée par le backend de la plateforme d'inscription ; chaque
 * application déclare dans `AppConfig.contact` l'URL de cette route et la boîte
 * support visée (canal e-mail Zammad) :
 *
 *   "contact": {
 *     "apiUrl": "https://plateformes.reserves-naturelles.org/api/contact/",
 *     "recipientEmail": "support@reserves-naturelles.org"
 *   }
 *
 * Le destinataire est validé côté serveur contre une liste blanche : une adresse
 * inconnue est refusée, la route ne peut pas servir de relais d'envoi.
 *
 * Tant qu'une application n'a pas renseigné `apiUrl`, on retombe sur le `mailto:`
 * historique — le sous-module étant partagé, la mise à jour peut être progressive.
 */
@Injectable({
  providedIn: 'root',
})
export class ContactService {
  constructor(private http: HttpClient) {}

  private get config(): ContactConfig {
    return ((AppConfig as { contact?: ContactConfig }).contact || {}) as ContactConfig;
  }

  /** Destinataire déclaré par l'application (boîte du canal mail Zammad). */
  getRecipientEmail(): string {
    return (this.config.recipientEmail || '').trim();
  }

  getApiUrl(): string {
    return (this.config.apiUrl || '').trim();
  }

  /** True si l'application est configurée d'une façon ou d'une autre. */
  isConfigured(): boolean {
    return !!this.getApiUrl() || !!this.getRecipientEmail();
  }

  /**
   * Envoie le message. Émet `true` quand le backend a pris le message en charge,
   * `false` quand le repli `mailto:` a ouvert le client mail de l'utilisateur
   * (aucune confirmation d'envoi n'est alors possible).
   */
  sendMessage(payload: ContactMessagePayload): Observable<boolean> {
    const apiUrl = this.getApiUrl();
    if (!apiUrl) {
      return of(this.openMailto(payload)).pipe(
        map((opened) => {
          if (!opened) {
            throw new Error('contact_not_configured');
          }
          return false;
        })
      );
    }

    return this.http
      .post(apiUrl, {
        email: (payload.email || '').trim(),
        name: (payload.name || '').trim(),
        subject: (payload.subject || '').trim(),
        message: (payload.message || '').trim(),
        app_name: AppConfig.appName || '',
        recipient: this.getRecipientEmail(),
      })
      .pipe(
        map(() => true),
        catchError((error) => throwError(() => error))
      );
  }

  /** Message d'erreur lisible à partir de la réponse du backend. */
  errorMessage(error: unknown): string {
    const status = (error as { status?: number })?.status;
    const detail = (error as { error?: { detail?: string } })?.error?.detail;
    if (status === 429) {
      return 'Trop de messages envoyés. Merci de réessayer plus tard.';
    }
    if (status === 503) {
      return 'Le formulaire de contact n’est pas disponible actuellement.';
    }
    if (status === 0) {
      return 'Service injoignable. Vérifiez votre connexion.';
    }
    return detail || 'L’envoi du message a échoué.';
  }

  /**
   * Repli historique : ouvre le client mail de l'utilisateur.
   * Utilisé tant qu'une application n'a pas configuré `contact.apiUrl`.
   */
  openMailto(payload: ContactMessagePayload): boolean {
    const to = this.getRecipientEmail();
    if (!to) {
      return false;
    }
    const email = (payload.email || '').trim();
    const subject = (payload.subject || '').trim();
    const message = (payload.message || '').trim();
    const name = (payload.name || '').trim();

    const bodyParts: string[] = [];
    if (name || email) {
      bodyParts.push(`Contact : ${[name, email].filter(Boolean).join(' — ')}`);
      bodyParts.push('');
    }
    bodyParts.push(message);
    if (AppConfig.appName) {
      bodyParts.push('');
      bodyParts.push(`— ${AppConfig.appName}`);
    }

    const params = new URLSearchParams();
    if (subject) {
      params.set('subject', subject);
    }
    params.set('body', bodyParts.join('\n'));

    // URLSearchParams encode les espaces en +, mailto préfère %20
    const query = params.toString().replace(/\+/g, '%20');
    window.location.href = `mailto:${to}?${query}`;
    return true;
  }
}
