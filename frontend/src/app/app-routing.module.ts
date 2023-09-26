import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LoginComponent } from './home-rnf/components/login/login.component';
import { LogoutComponent } from './home-rnf/components/logout/logout.component';
import { NavHomeComponent } from './home-rnf/components/nav-home/nav-home.component';
import { LazyDialogLoader } from './home-rnf/services/lazy-dialog-loader.service';
import { LogoutLinkService } from './home-rnf/services/logout-link.service';
import { HomeComponent } from './home/home.component';
import { SignUpComponent } from './sign-up/sign-up.component';

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
        path: 'logout', // Ici seulement pour angular, mais toujour redirigé dans le canActivate 
        component: LogoutComponent, 
        canActivate: [ LogoutLinkService ] 
      }, 
      { 
        path: 'login', 
        component: LoginComponent, 
        canActivate: [ LazyDialogLoader ] 
      } 
    ] 
  } ,
  {
    path: 'inscription',
    component: SignUpComponent
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
