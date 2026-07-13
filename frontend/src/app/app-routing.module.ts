import { NgModule } from '@angular/core';
import { RouterModule, Routes, mapToCanActivate } from '@angular/router';
import { LoginComponent } from './home-rnf/components/login/login.component';
import { LogoutComponent } from './home-rnf/components/logout/logout.component';
import { NavHomeComponent } from './home-rnf/components/nav-home/nav-home.component';
import { ResetPasswordComponent } from './components/reset-password/reset-password.component';
import { LazyDialog } from './home-rnf/services/lazy-dialog-loader.service';
import { LogoutLinkService } from './home-rnf/services/logout-link.service';
import { HomeComponent } from './components/home/home.component';
import { SignUpComponent } from './components/sign-up/sign-up.component';
import { MoncompteComponent } from './components/moncompte/moncompte.component';
import { AuthGuard } from './home-rnf/services/auth-guard.service';
import { ForgotPasswordComponent } from './home-rnf/components/forgot-password/forgot-password.component';
import { AuthCallbackComponent } from './components/auth-callback/auth-callback.component';
import { AdminDashboardComponent } from './components/admin-dashboard/admin-dashboard.component';
import { NotificationsComponent } from './components/notifications/notifications.component';
import { AdminGuard } from './home-rnf/services/admin-guard.service';

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
        component: HomeComponent
      },
      {
        path: 'mot-de-passe-oublie',
        component: ForgotPasswordComponent
      },
      { 
        path: 'logout', // Ici seulement pour angular, mais toujour redirigé dans le canActivate 
        component: LogoutComponent, 
        canActivate: mapToCanActivate([LogoutLinkService]),
      }, 
      { 
        path: 'login', 
        component: LoginComponent, 
        canActivate: [LazyDialog],
      },
      { 
        path: 'mon-compte', 
        component: MoncompteComponent, 
        canActivate: [AuthGuard],
      },
      {
        path: 'notifications',
        component: NotificationsComponent,
        canActivate: [AuthGuard],
      },
      {
        path: 'admin',
        component: AdminDashboardComponent,
        canActivate: [AdminGuard],
      },
    ] 
  } ,
  {
    path: 'inscription',
    component: SignUpComponent
  } ,
  {
    path: 'nouveau-mot-de-passe',
    component: ResetPasswordComponent
  },
  {
    path: 'auth/callback',
    component: AuthCallbackComponent,
  },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
