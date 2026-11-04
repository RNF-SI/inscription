import { NgModule } from '@angular/core';
import { RouterModule, Routes, mapToCanActivate } from '@angular/router';
import { LoginComponent } from './core/components/login/login.component';
import { LogoutComponent } from './core/components/logout/logout.component';
import { NavHomeComponent } from './core/components/nav-home/nav-home.component';
import { ResetPasswordComponent } from './components/reset-password/reset-password.component';
import { LazyDialog } from './core/auth/lazy-dialog-loader.service';
import { LogoutLinkService } from './core/auth/logout-link.service';
import { HomeComponent } from './components/home/home.component';
import { SignUpComponent } from './components/sign-up/sign-up.component';
import { MoncompteComponent } from './components/moncompte/moncompte.component';
import { AuthGuard } from './core/auth/auth-guard.service';
import { ForgotPasswordComponent } from './core/components/forgot-password/forgot-password.component';
import { AuthCallbackComponent } from './components/auth-callback/auth-callback.component';
import { AdminDashboardComponent } from './components/admin-dashboard/admin-dashboard.component';
import { NotificationsComponent } from './components/notifications/notifications.component';
import { AdminGuard } from './core/auth/admin-guard.service';

// const routes: Routes = [
//   {
//     path: '',
//     component: HomeComponent
//   },
//   {
//     path: 'inscription',
//     component: SignUpComponent
//   }
// ];

const routes: Routes = [ 
  { 
    path: '', 
    component: NavHomeComponent, 
    children: [ 
      {
        path: '',
        component: HomeComponent,
        title: 'Accueil'
      },
      {
        path: 'mot-de-passe-oublie',
        component: ForgotPasswordComponent,
        title: 'Mot de passe oublié'
      },
      { 
        path: 'logout', // Ici seulement pour angular, mais toujour redirigé dans le canActivate 
        component: LogoutComponent, 
        canActivate: mapToCanActivate([LogoutLinkService]),
        title: 'Déconnexion',
      }, 
      { 
        path: 'login', 
        component: LoginComponent, 
        canActivate: [LazyDialog],
        title: 'Connexion',
      },
      { 
        path: 'mon-compte', 
        component: MoncompteComponent, 
        canActivate: [AuthGuard],
        title: 'Mon compte',
      },
      {
        path: 'notifications',
        component: NotificationsComponent,
        canActivate: [AuthGuard],
        title: 'Notifications',
      },
      {
        path: 'admin',
        component: AdminDashboardComponent,
        canActivate: [AdminGuard],
        title: 'Administration',
      },
    ] 
  } ,
  {
    path: 'inscription',
    component: SignUpComponent,
    title: 'Inscription'
  } ,
  {
    path: 'nouveau-mot-de-passe',
    component: ResetPasswordComponent,
    title: 'Nouveau mot de passe'
  },
  {
    path: 'auth/callback',
    component: AuthCallbackComponent,
    title: 'Connexion en cours',
  },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
