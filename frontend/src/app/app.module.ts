import { NgModule, provideZoneChangeDetection } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { SignUpComponent } from './components/sign-up/sign-up.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip'
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import {MatCardModule} from '@angular/material/card';
import {MatGridListModule} from '@angular/material/grid-list';
import { MatInputModule } from  '@angular/material/input';
import { MatSelectModule } from  '@angular/material/select';
import { NgxMatSelectSearchModule } from 'ngx-mat-select-search';


import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { HttpClientModule, HTTP_INTERCEPTORS } from '@angular/common/http';
import { NgbModule } from '@ng-bootstrap/ng-bootstrap';
import { RouterModule } from '@angular/router';
import { HomeComponent } from './components/home/home.component';
import { FontAwesomeModule, FaIconLibrary } from '@fortawesome/angular-fontawesome';
import { RandomOrderPipe } from './pipes/random-order.pipe';

import { faKey, faUserPlus, faArrowUpRightFromSquare, faCheck, faClock, faBan } from '@fortawesome/free-solid-svg-icons';
import { faFacebook, faInstagram, faGithub, faLinkedin} from '@fortawesome/free-brands-svg-icons';
import { fab } from '@fortawesome/free-brands-svg-icons';
import { far } from '@fortawesome/free-regular-svg-icons';
import { fas } from '@fortawesome/free-solid-svg-icons';

import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatSnackBarModule } from '@angular/material/snack-bar';
import { LoginComponent } from './core/components/login/login.component';
import { LogoutComponent } from './core/components/logout/logout.component';
import { NavHomeComponent } from './core/components/nav-home/nav-home.component';
import { ForgotPasswordComponent } from './core/components/forgot-password/forgot-password.component';
import { LoadingSpinnerComponent } from './core/components/loading-spinner/loading-spinner.component';
import { ToastComponent } from './core/components/toast/toast.component';
import { InputErrorPipe } from './core/pipes/input-error.pipe';
import { MyCustomInterceptor } from './services/http.interceptor';
import { ResetPasswordComponent } from './components/reset-password/reset-password.component';
import { NgMultiSelectDropDownModule } from 'ng-multiselect-dropdown';
import { MoncompteComponent } from './components/moncompte/moncompte.component';
import { SearchPipe } from './pipes/search.pipe';
import { AuthCallbackComponent } from './components/auth-callback/auth-callback.component';
import { AdminDashboardComponent } from './components/admin-dashboard/admin-dashboard.component';
import { NotificationsComponent } from './components/notifications/notifications.component';
import { NotificationBadgeService } from './core/services/notification-badge.service';
import { InscriptionNotificationBadgeService } from './services/inscription-notification-badge.service';
import { ImageCropperComponent } from 'ngx-image-cropper';

@NgModule({
  declarations: [
    AppComponent,
    SignUpComponent,
    HomeComponent,
    RandomOrderPipe,
    SearchPipe,
    ResetPasswordComponent,
    MoncompteComponent,
    AuthCallbackComponent,
    AdminDashboardComponent,
    NotificationsComponent,
    // Socle internalisé (ex-sous-module home-rnf), cf. src/app/core
    NavHomeComponent,
    LoginComponent,
    LogoutComponent,
    ForgotPasswordComponent,
    LoadingSpinnerComponent,
    ToastComponent,
    InputErrorPipe,
  ],
  imports: [
    HttpClientModule,
    BrowserModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    MatDividerModule,
    MatIconModule,
    MatTooltipModule,
    MatProgressSpinnerModule,
    MatCardModule,
    MatGridListModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    NgxMatSelectSearchModule,
    FormsModule,
    ReactiveFormsModule,
    MatSnackBarModule,
    NgbModule,
    RouterModule,
    FontAwesomeModule,
    MatMenuModule,
    MatToolbarModule,
    MatDialogModule,
    MatProgressBarModule,
    MatFormFieldModule,
    MatAutocompleteModule,
    NgMultiSelectDropDownModule.forRoot(),
    ImageCropperComponent,
  ],
  providers: [
    provideZoneChangeDetection(),
    { provide: HTTP_INTERCEPTORS, useClass: MyCustomInterceptor, multi: true },
    { provide: NotificationBadgeService, useClass: InscriptionNotificationBadgeService },
    // LoginComponent est routé, pas ouvert en dialogue : bouchons repris de HomeRnfModule.
    { provide: MAT_DIALOG_DATA, useValue: {} },
    { provide: MatDialogRef, useValue: {} }
  ],
  bootstrap: [AppComponent]
})
export class AppModule {
  constructor(library: FaIconLibrary) {
    library.addIconPacks(fab, fas, far);
    library.addIcons(
      faKey,
      faUserPlus,
      faArrowUpRightFromSquare,
      faCheck,
      faClock,
      faBan,
      faFacebook,
      faInstagram,
      faGithub,
      faLinkedin
    );
  }
 }
