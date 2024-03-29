import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LoginComponent } from './home-rnf/components/login/login.component';
import { LogoutComponent } from './home-rnf/components/logout/logout.component';
import { NavHomeComponent } from './home-rnf/components/nav-home/nav-home.component';
import { ResetPasswordComponent } from './components/reset-password/reset-password.component';
import { LazyDialogLoader } from './home-rnf/services/lazy-dialog-loader.service';
import { LogoutLinkService } from './home-rnf/services/logout-link.service';
import { HomeComponent } from './components/home/home.component';
import { SignUpComponent } from './components/sign-up/sign-up.component';
import { MoncompteComponent } from './components/moncompte/moncompte.component';
import { AuthGuardService } from './home-rnf/services/auth-guard.service';
import { ForgotPasswordComponent } from './home-rnf/components/forgot-password/forgot-password.component';

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
        canActivate: [ LogoutLinkService ] 
      }, 
      { 
        path: 'login', 
        component: LoginComponent, 
        canActivate: [ LazyDialogLoader ] 
      },
      { 
        path: 'mon-compte', 
        component: MoncompteComponent, 
        canActivate: [ AuthGuardService]
      }
    ] 
  } ,
  {
    path: 'inscription',
    component: SignUpComponent
  } ,
  {
    path: 'nouveau-mot-de-passe',
    component: ResetPasswordComponent
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
